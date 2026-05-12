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
from app.scroller.graph import create_crawl_graph, create_cluster_graph, create_comparison_graph
from app.scroller.nodes import ScrollerNodes 
from app.domains.articles.service import ArticleService
from app.core.logger import logger, log_llm_event, start_job_logging, stop_job_logging, finalize_job_log

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

TARGET_PRESS_DICT = {
    # 🔵 진보/개혁 (Progressive) - 4개
    "한겨레": "028", "경향신문": "032", "MBC": "214", "JTBC": "437",
    
    # 🔴 보수/경제 (Conservative) - 4개
    "조선일보": "023", "동아일보": "020", "중앙일보": "025", "문화일보": "021",
    
    # ⚪ 중도/온건 (Centrist) - 4개
    "한국일보": "046", "국민일보": "005", "서울신문": "081", "세계일보": "022"
}
DAYS_TO_CRAWL = 2

class ScrollerService:
    def __init__(self, db: Session):
        self.repo = ScrollerRepository(db)
        self.db = db
        # 서버 기동 시 또는 서비스 객체 생성 시 그래프 컴파일
        self.crawl_app = create_crawl_graph(db)
        self.cluster_app = create_cluster_graph(db)
        self.comparison_app = create_comparison_graph(db)
        self.article_service = ArticleService(db)


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
    def execute_clustering(self, mode: str = None, article_mode: str = "editorial") -> ClusterResponse:
        """
        미분류 기사들을 군집화하고 이슈 이름을 생성하는 워크플로우를 실행합니다.
        - mode: 제공되지 않을 경우 DB의 SystemSettings 값을 따름.
        - article_mode: 'editorial' 또는 'politics'
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
            "article_mode": article_mode,
            "unclustered_articles": [],
            "clustered_topics": [],
            "saved_issue_count": 0,
            "messages": [],
            "error": ""
        }
        
        # 체크포인팅을 위한 설정 (article_mode 별로 다른 thread_id 사용하여 캐시 충돌 방지)
        config = {"configurable": {"thread_id": f"scroller_cluster_{article_mode}"}}
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
    # 비교 분석 비즈니스 로직 (LangGraph 연동)
    # ==========================================
    def execute_comparison_pipeline(self, issue_id: int, mode: str = None) -> dict:
        """
        특정 이슈에 대한 언론사별 주장을 추출하고 비교 비평을 생성하는 워크플로우를 실행합니다.
        """
        if not mode:
            setting = self.db.query(SystemSettings).first()
            mode = setting.llm_mode if setting else "gemini_only"

        logger.info(f"⚖️ 언론사별 주장 비교 분석 워크플로우 시작 (Issue ID: {issue_id}, Mode: {mode})")
        
        handler_id, log_path = start_job_logging("comparison")
        session_logger = logger.bind(job_type="comparison")

        initial_state = {
            "llm_mode": mode,
            "issue_id": issue_id,
            "articles": [],
            "extracted_claims": [],
            "final_analysis": "",
            "messages": [],
            "error": ""
        }
        
        config = {"configurable": {"thread_id": f"comparison_{issue_id}"}}
        try:
            final_state = self.comparison_app.invoke(initial_state, config=config)
        except Exception as e:
            stop_job_logging(handler_id)
            finalize_job_log(log_path, "failed")
            raise e
        
        if final_state.get("error"):
            session_logger.error(f"❌ 비교 분석 중 오류 발생: {final_state['error']}")
            stop_job_logging(handler_id)
            finalize_job_log(log_path, "failed")
            return {"status": "error", "message": final_state["error"]}
            
        # 성공적으로 완료되면 flush된 DB 변경사항을 커밋합니다.
        try:
            self.db.commit()
            session_logger.success(f"💾 비교 분석 결과 DB 커밋 완료 (Issue ID: {issue_id})")
        except Exception as e:
            self.db.rollback()
            session_logger.error(f"❌ DB 커밋 중 오류 발생: {e}")
            raise e

        session_logger.success(f"✅ 비교 분석 완료 (Issue ID: {issue_id})")
        stop_job_logging(handler_id)
        finalize_job_log(log_path, "success")
        
        return {
            "status": "success",
            "final_analysis": final_state.get("final_analysis", ""),
            "extracted_claims_count": len(final_state.get("extracted_claims", []))
        }

    def save_article_claim(self, issue_id: int, article_id: int, press: str, claim: str, evidence: str):
        """에이전트 1의 추출 결과를 저장합니다."""
        return self.article_service.save_article_claim(issue_id, article_id, press, claim, evidence)

    def get_claims_by_issue(self, issue_id: int):
        """이슈 ID로 저장된 주장 데이터를 조회합니다."""
        return self.article_service.get_claims_by_issue(issue_id)

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
            # 안전하게 기존 모드 조회 (데이터가 없을 경우 "unknown" 처리)
            existing = self.db.query(SystemSettings).filter(SystemSettings.id == 1).first()
            old_mode = existing.llm_mode if existing else "unknown"

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
            gemini_model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")
            model = genai.GenerativeModel(gemini_model_name)
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
            log_llm_event("NLPSearch", f"Requesting {gemini_model_name} for briefing", details=prompt)
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

        # ── 이슈 검색 ──────────────────────────────────────────────────────────
        matched_issue_objects = self.repo.search_issues_by_keyword(user_query, limit=10)
        matched_issues = [
            {
                "id": issue.id,
                "name": issue.name,
                "description": issue.description,
                "issue_type": issue.issue_type,
                "created_at": issue.created_at.strftime("%Y-%m-%d") if issue.created_at else None,
            }
            for issue in matched_issue_objects
        ]
        logger.info(f"📌 '{user_query}' 관련 이슈 {len(matched_issues)}건 검색됨")
        # ───────────────────────────────────────────────────────────────────────

        if not items:
            logger.info(f"ℹ️ '{user_query}' 관련 검색 결과 없음")
            return {
                "success": False,
                "message": "내부 DB에 해당 키워드를 포함한 기사가 없습니다.",
                "data": {"matched_issues": matched_issues}
            }

        processed_articles = []
        source_counter = Counter()

        for idx, item in enumerate(items):
            press_name = item.publisher.name if getattr(item, 'publisher', None) else "알 수 없음"
            content = item.body.raw_content if getattr(item, 'body', None) else ""
            
            art_data = {
                "article_db_id": item.id,           # 실제 DB article id
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
                "id": art["article_db_id"],          # 실제 DB article id로 교체
                "title": art['title'],
                "source": art['source'],
                "description": art['description'],
                "link": art['link'],
                "pubDate": art['pubDate'],
                "relevance_score": 0.0,
                "matching_keywords": matched
            })

        # ai_summary 파싱 (프론트엔드 연동을 위한 구조화)
        ai_summary_text = briefing.get('summary_content', '')
        blocks = [b.strip() for b in ai_summary_text.split('\n\n') if b.strip()]
        
        structured_summary = {
            "intro": "",
            "topics": []
        }
        
        for i, block in enumerate(blocks):
            # 첫 문단이 매우 짧고(예: "다음과 같습니다.") 첫째/1. 등으로 시작하지 않으면 서론으로 간주 (80자 미만)
            is_intro = False
            if i == 0 and len(block) < 80 and not any(block.startswith(prefix) for prefix in ["첫째", "1.", "-", "하나"]):
                is_intro = True
                
            if is_intro:
                structured_summary["intro"] = block
            else:
                parts = block.split('. ', 1)
                if len(parts) > 1:
                    title = parts[0] + "."
                    content = parts[1]
                else:
                    title = block
                    content = block
                
                clean_title = title
                # 숫자나 순서 키워드 제거
                for prefix in ["첫째, ", "둘째, ", "셋째, ", "넷째, ", "다섯째, ", "1. ", "2. ", "3. ", "첫번째, ", "두번째, ", "세번째, "]:
                    if clean_title.startswith(prefix):
                        clean_title = clean_title[len(prefix):].strip()
                        break
                
                # 불필요한 접속사 추가 제거
                for prefix in ["한편, ", "이와 별도로, ", "또한, ", "마지막으로, ", "끝으로, ", "더불어, ", "그리고, "]:
                    if clean_title.startswith(prefix):
                        clean_title = clean_title[len(prefix):].strip()
                        break
                
                # 주제 문단에 포함된 키워드 매칭 (검색어 원어 제외하여 변별력 확보)
                topic_keywords = [k for k in final_keywords if k in block and k != user_query]
                
                related_article_ids = []
                for art in formatted_articles:
                    # 기사의 키워드 중에서도 검색어 원어 제거
                    art_kws = [k for k in art['matching_keywords'] if k != user_query]
                    
                    # 검색어 제외하고 남은 키워드끼리 겹치면 해당 기사 매칭
                    if set(topic_keywords) & set(art_kws):
                        related_article_ids.append(art['id'])
                
                # 만약 걸러낸 키워드가 하나도 없어 매칭이 안됐다면, 원어 포함해서 최소한 하나라도 보여주기 (예비)
                if not related_article_ids:
                    fallback_topic_keywords = [k for k in final_keywords if k in block]
                    for art in formatted_articles:
                        if set(fallback_topic_keywords) & set(art['matching_keywords']):
                            related_article_ids.append(art['id'])
                
                structured_summary["topics"].append({
                    "id": len(structured_summary["topics"]) + 1,
                    "title": clean_title,
                    "content": content,
                    "related_articles": list(dict.fromkeys(related_article_ids)) # 중복 안전장치
                })

        return {
            "success": True,
            "data": {
                "original_query": user_query,
                "matched_issues": matched_issues,   # ← 이슈 검색 결과 추가
                "generated_keywords": final_keywords,
                "ai_summary": ai_summary_text,
                "ai_summary_structured": structured_summary,
                "total_results": len(formatted_articles),
                "articles": formatted_articles,
                "by_source": dict(source_counter)
            }
        }
