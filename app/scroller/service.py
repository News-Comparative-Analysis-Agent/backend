# app/scroller/service.py
import os
import json
import logging
from datetime import datetime, timedelta
from collections import Counter
import google.generativeai as genai
from sqlalchemy.orm import Session

from app.scroller.repository import ScrollerRepository
from sqlalchemy import func
from app.scroller.schemas import CrawlResponse, ClusterResponse, ResetResponse, LLMMode
from app.domains.system.models import SystemSettings
from app.scroller.graph import create_crawl_graph, create_cluster_graph
from app.scroller.nodes import ScrollerNodes 
from app.core.logger import logger, log_llm_event, start_job_logging, stop_job_logging, finalize_job_log

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

TARGET_PRESS_DICT = {
    "한겨레": "028", "경향신문": "032", 
    "조선일보": "023", "동아일보": "020", "연합뉴스": "001"
}
DAYS_TO_CRAWL = 4

class ScrollerService:
    def __init__(self, db: Session):
        self.repo = ScrollerRepository(db)
        self.db = db
        # 서버 기동 시 또는 서비스 객체 생성 시 그래프 컴파일
        self.crawl_app = create_crawl_graph(db)
        self.cluster_app = create_cluster_graph(db)


    # ==========================================
    # 크롤링 비즈니스 로직 (LangGraph 연동)
    # ==========================================
    def execute_news_crawling(self, mode: str = None) -> CrawlResponse:
        """
        네이버 뉴스를 크롤링하고 AI 분석을 수행하는 전체 워크플로우를 실행합니다.
        - mode: 'gemini_only', 'local_priority', 'local_only' 중 선택. 
                제공되지 않을 경우 DB의 SystemSettings 값을 따름.
        """
        if not mode:
            setting = self.db.query(SystemSettings).first()
            mode = setting.llm_mode if setting else "gemini_only"

        logger.info(f"🔄 뉴스 크롤링 워크플로우 시작 (Mode: {mode})")
        
        # 세션 로그 시작
        handler_id, log_path = start_job_logging("crawler")
        # 이 세션에서 발생하는 모든 로그는 해당 파일로 스트리밍됨
        session_logger = logger.bind(job_type="crawler")

        initial_state = {
            "llm_mode": mode,
            "raw_articles": [],
            "analyzed_articles": [],
            "saved_count": 0,
            "skipped_count": 0,
            "messages": [],
            "error": ""
        }
        
        # 체크포인팅을 위한 설정 (고유 스레드 ID 부여)
        config = {"configurable": {"thread_id": "scroller_crawl_session"}}
        try:
            final_state = self.crawl_app.invoke(initial_state, config=config)
        except Exception as e:
            stop_job_logging(handler_id)
            finalize_job_log(log_path, "failed")
            raise e
        
        # 2. 결과 처리
        saved = final_state.get("saved_count", 0)
        skipped = final_state.get("skipped_count", 0)
        
        if final_state.get("error"):
            session_logger.error(f"❌ 크롤링 중 오류 발생: {final_state['error']}")
            stop_job_logging(handler_id)
            finalize_job_log(log_path, "failed")
            return CrawlResponse(
                status="error",
                message=final_state["error"],
                saved_count=0,
                skipped_count=0
            )
            
        msgs = final_state.get("messages", [])
        result_msg = "\n".join(msgs) # 모든 메시지를 줄바꿈으로 합침

        session_logger.success(f"✅ 뉴스 크롤링 완료: 신규 저장 {saved}건, 중복 스킵 {skipped}건")
        
        stop_job_logging(handler_id)
        finalize_job_log(log_path, "success")

        return CrawlResponse(
            status="success",
            message=result_msg,
            saved_count=saved,
            skipped_count=skipped
        )

    # ==========================================
    # 클러스터링 비즈니스 로직 (LangGraph 연동)
    # ==========================================
    def execute_clustering(self, mode: str = None) -> ClusterResponse:
        """
        미분류 기사들을 군집화하고 이슈 이름을 생성하는 워크플로우를 실행합니다.
        - mode: 제공되지 않을 경우 DB의 SystemSettings 값을 따름.
        """
        if not mode:
            setting = self.db.query(SystemSettings).first()
            mode = setting.llm_mode if setting else "gemini_only"
            
        logger.info(f"📊 이슈 클러스터링 워크플로우 시작 (Mode: {mode})")
        
        # 세션 로그 시작
        handler_id, log_path = start_job_logging("cluster")
        session_logger = logger.bind(job_type="cluster")

        initial_state = {
            "llm_mode": mode,
            "unclustered_articles": [],
            "clustered_topics": [],
            "saved_issue_count": 0,
            "messages": [],
            "error": ""
        }
        
        # 체크포인팅을 위한 설정 (고유 스레드 ID 부여)
        config = {"configurable": {"thread_id": "scroller_cluster_session"}}
        try:
            final_state = self.cluster_app.invoke(initial_state, config=config)
        except Exception as e:
            stop_job_logging(handler_id)
            finalize_job_log(log_path, "failed")
            raise e
        
        # 2. 결과 처리
        saved_issues = final_state.get("saved_issue_count", 0)
        
        if final_state.get("error"):
            session_logger.error(f"❌ 클러스터링 중 오류 발생: {final_state['error']}")
            stop_job_logging(handler_id)
            finalize_job_log(log_path, "failed")
            return ClusterResponse(
                status="error",
                message=final_state["error"],
                saved_issue_count=0
            )
            
        msgs = final_state.get("messages", [])
        result_msg = "\n".join(msgs) # 모든 메시지를 줄바꿈으로 합침

        session_logger.success(f"✅ 이슈 클러스터링 완료: 생성된 이슈 {saved_issues}건")

        stop_job_logging(handler_id)
        finalize_job_log(log_path, "success")
            
        return ClusterResponse(
            status="success",
            message=result_msg,
            saved_issue_count=saved_issues
        )

    # ==========================================
    # 초기화 비즈니스 로직
    # ==========================================
    def execute_truncate(self) -> ResetResponse:
        try:
            self.repo.truncate_all_data()
            self.repo.db.commit()
            logger.warning("🗑️ 데이터베이스 초기화(Truncate)가 실행되었습니다.")
            return ResetResponse(status="success", message="모든 데이터가 삭제되고 PK 1번으로 리셋되었습니다.")
        except Exception as e:
            self.repo.db.rollback()
            logger.error(f"❌ 데이터베이스 초기화 실패: {e}")
            return ResetResponse(status="error", message=f"삭제 오류: {e}")


    def update_llm_mode(self, mode: str) -> str:
        """시스템 LLM 모드를 업데이트하고 결과를 반환합니다."""
        try:
            old_mode = self.db.query(SystemSettings).first().llm_mode
            settings = self.repo.update_system_llm_mode(mode)
            self.db.commit()
            logger.info(f"⚙️ 시스템 LLM 모드 변경: {old_mode} -> {settings.llm_mode}")
            return settings.llm_mode
        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ LLM 모드 변경 실패: {e}")
            raise e

# ==========================================
# NLP 검색 로직 (기존 nlp_search.py 대체)
# ==========================================
class NLPSearchService:
    def __init__(self, db: Session):
        self.repo = ScrollerRepository(db)
        self.nodes = ScrollerNodes(db) # JSON 파싱 등 공통 기능 활용용

    def generate_briefing(self, query, articles_data):
        try:
            model = genai.GenerativeModel('gemini-2.0-flash')
            context_text = ""
            for i, art in enumerate(articles_data):
                content = art.get('full_text', art['description']) 
                context_text += f"[{i+1}] 언론사: {art['source']} | 제목: {art['title']}\n내용: {content[:1000]}\n\n"

            prompt = f"""
            당신은 정치/사회 이슈 전문 분석가입니다.
            사용자가 요청한 검색어: "{query}"
            
            아래 제공된 {len(articles_data)}개의 뉴스 기사들을 종합적으로 분석하여 '이슈 브리핑 보고서'를 작성해주세요.
            
            [분석 지침]
            1. 특정 언론사의 시각에 치우치지 말고, 중립적인 입장에서 서술하십시오.
            2. 논란이 있는 이슈라면 '찬성/반대' 또는 '여당/야당/정부'의 입장을 구분하여 정리하십시오.
            3. 가장 중요한 핵심 흐름을 3문단 이내로 요약하십시오.

            [입력 데이터]
            {context_text}

            [출력 형식 (JSON)]
            {{
                "summary_content": "종합적인 요약 내용 (마크다운 형식 가능, 줄바꿈은 \\n)",
                "keywords": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"]
            }}
            """
            log_llm_event("NLPSearch", "Requesting gemini-2.0-flash for briefing", details=prompt)
            response = model.generate_content(prompt)
            log_llm_event("NLPSearch", "Response received", details=response.text)
            parsed = self.nodes._parse_llm_json(response.text)
            return parsed
        except Exception as e:
            print(f"⚠️ 브리핑 생성 실패: {e}")
            return None

    def execute_search_briefing(self, user_query):
        logger.info(f"🔍 '{user_query}' 관련 기사 내부 DB 검색 중...")
        items = self.repo.search_articles_by_keyword(user_query, limit=15)
        if not items: 
            logger.info(f"ℹ️ '{user_query}' 관련 검색 결과 없음")
            return {"success": False, "message": "내부 DB에 해당 키워드를 포함한 기사가 없습니다."}

        processed_articles = []
        source_counter = Counter()

        for idx, item in enumerate(items):
            press_name = item.publisher.name if getattr(item, 'publisher', None) else "알 수 없음"
            content = item.body.raw_content if getattr(item, 'body', None) else ""
            
            art_data = {
                "title": item.title,
                "link": item.url,
                "description": content[:150] + "...",
                "pubDate": item.published_at.strftime("%Y-%m-%d %H:%M:%S") if item.published_at else "",
                "source": press_name
            }
            if idx < 3:
                # 상위 3개는 본문을 제공
                if content:
                    art_data['full_text'] = content
            processed_articles.append(art_data)
            source_counter[press_name] += 1

        briefing = self.generate_briefing(user_query, processed_articles)
        if not briefing:
             return {"success": False, "message": "AI 브리핑 생성에 실패했습니다."}

        final_keywords = briefing.get('keywords', [])
        formatted_articles = []
        
        for idx, art in enumerate(processed_articles):
            matched = [k for k in final_keywords if k in art['title'] or k in art['description']]
            formatted_articles.append({
                "id": f"news_{idx+1:03d}",
                "title": art['title'],
                "source": art['source'],
                "description": art['description'],
                "link": art['link'],
                "pubDate": art['pubDate'],
                "relevance_score": 0.0,
                "matching_keywords": matched
            })

        return {
            "success": True,
            "data": {
                "original_query": user_query,
                "generated_keywords": final_keywords,
                "ai_summary": briefing.get('summary_content', ''),
                "total_results": len(formatted_articles),
                "articles": formatted_articles,
                "by_source": dict(source_counter)
            }
        }