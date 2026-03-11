from datetime import datetime, timedelta
import time
import random
import json
import requests
import concurrent.futures
import pandas as pd
from bs4 import BeautifulSoup
import google.generativeai as genai
import os
from sqlalchemy.orm import Session
import numpy as np
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from hdbscan import HDBSCAN
from umap import UMAP
from bertopic import BERTopic
import logging
import gc
import os
from dotenv import load_dotenv

from app.scroller.repository import ScrollerRepository
from app.agents.state import CrawlState, ClusterState, ComparisonState
from app.core.logger import logger, log_llm_event


# .env 로드
load_dotenv()
env = os.environ

TARGET_PRESS_DICT = {
    # 🔵 진보/개혁 (Progressive) - 7개
    "한겨레": "028", "경향신문": "032", "오마이뉴스": "047", "MBC": "214",
    "JTBC": "437", "노컷뉴스": "079", "프레시안": "002",
    
    # 🔴 보수/경제 (Conservative) - 7개
    "조선일보": "023", "동아일보": "020", "중앙일보": "025", "문화일보": "021",
    "한국경제": "015", "세계일보": "022", "TV조선": "448",
    
    # ⚪ 중도/팩트/통신 (Centrist & Fact) - 6개
    "연합뉴스": "001", "한국일보": "046", "YTN": "052",
    "뉴스1": "421", "뉴시스": "003", "SBS": "055"
}
DAYS_TO_CRAWL = 4

# 온프레미스 LLM 서버 설정 (OpenAI 호환 API 구조)
LOCAL_LLM_SERVERS = {
    # 기사 요약 및 정치 성향 판단 모델 
    "7B_1":   f"http://{env.get('LLM_SERVER_IP')}:{env.get('PORT_7B_1')}/{env.get('LLM_SERVER_API_URI')}",

    # 비평기사 작성 모델
    "7B_2":   f"http://{env.get('LLM_SERVER_IP')}:{env.get('PORT_7B_2')}/{env.get('LLM_SERVER_API_URI')}",
}

class ScrollerNodes:
    """
    LangGraph의 각 단계(Node)에서 실행될 구체적인 파이썬 함수들의 집합입니다.
    네이버 뉴스 크롤링, BERTopic 군집화, Gemini AI 분석 등의 핵심 로직을 포함합니다.
    """
    
    # AI 모델(BERTopic/SBERT) 캐싱을 위한 클래스 변수 (싱글톤 패턴)
    # 수 GB의 모델을 매번 로드하지 않도록 메모리에 고정하여 사용합니다.
    _topic_model = None

    def __init__(self, db: Session):
        """
        Args:
            db (Session): 작업을 위한 데이터베이스 세션
        """
        self.repo = ScrollerRepository(db)
        from app.domains.articles.service import ArticleService
        self.article_service = ArticleService(db)

    def _get_kst_now(self):
        """
        한국 표준시(KST) 기준 현재 시간을 반환합니다.
        서버 환경에 상관없이 일관된 날짜 처리를 위해 사용합니다 (UTC+9 적용).
        """
        return datetime.utcnow() + timedelta(hours=9)

    def _parse_llm_json(self, text: str) -> dict:
        """
        AI가 반환한 텍스트에서 JSON 블록을 추출하여 파싱합니다.
        제미나이뿐만 아니라 로컬 LLM의 응답도 처리할 수 있도록 공통화하였습니다.
        """
        try:
            result_text = text.strip()
            # 마크다운 코드 블록 제거 로직
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].strip()
            return json.loads(result_text)
        except Exception as e:
            logger.error(f"JSON 파싱 실패: {e}\n원본 텍스트: {text}")
            return None

    def _call_local_llm(self, model_size: str, prompt: str, json_mode: bool = False) -> str:
        """
        온프레미스 로컬 LLM 서버에 요청을 보냅니다.
        """
        url = LOCAL_LLM_SERVERS.get(model_size)
        if not url:
            raise ValueError(f"지원하지 않는 모델 사이즈: {model_size}")
            
        payload = {
            "model": f"local-{model_size}",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        try:
            log_llm_event("LocalLLM", f"Requesting {model_size}", details=f"URL: {url}\nPayload: {json.dumps(payload, ensure_ascii=False)}")
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            content = result['choices'][0]['message']['content']
            
            # 토큰 정보 추출 (OpenAI 호환 포맷)
            usage = result.get('usage', {})
            token_info = {
                'prompt_tokens': usage.get('prompt_tokens', 0),
                'completion_tokens': usage.get('completion_tokens', 0)
            }
            
            log_llm_event("LocalLLM", f"Response received from {model_size}", details=content, token_info=token_info)
            return content
        except Exception as e:
            log_llm_event("LocalLLM", f"Error: {e}", details=str(e))
            logger.error(f"로컬 LLM({model_size}) 호출 실패: {e}")
            raise e

    def _call_llm(self, prompt: str, model_size: str, state: dict) -> dict:
        """
        llm_mode에 따라 제미나이 또는 로컬 LLM을 호출합니다.
        """
        mode = state.get("llm_mode", "gemini_only")
        
        # 1. 로컬 Only 모드
        if mode == "local_only":
            content = self._call_local_llm(model_size, prompt)
            return self._parse_llm_json(content)
            
        # 2. 제미나이 Only 모드
        if mode == "gemini_only":
            return self._call_gemini(prompt)
            
        # 3. 하이브리드 모드 (로컬 우선 -> 실패 시 제미나이)
        if mode == "local_priority":
            try:
                content = self._call_local_llm(model_size, prompt)
                parsed = self._parse_llm_json(content)
                if parsed: return parsed
                raise ValueError("로컬 LLM 응답 파싱 실패")
            except Exception as e:
                logger.warning(f"로컬 LLM 실패로 인해 제미나이로 폴백합니다: {e}")
                return self._call_gemini(prompt)
        
        return self._call_gemini(prompt)

    def _call_gemini(self, prompt: str) -> dict:
        """
        제미나이 API를 호출합니다.
        """
        try:
            log_llm_event("Gemini", "Requesting gemini-2.0-flash", details=prompt)
            model = genai.GenerativeModel('gemini-2.0-flash')
            response = model.generate_content(prompt)
            
            # 토큰 정보 추출 (Gemini 포맷)
            usage = response.usage_metadata
            token_info = {
                'prompt_tokens': usage.prompt_token_count,
                'completion_tokens': usage.candidates_token_count
            }
            
            log_llm_event("Gemini", "Response received", details=response.text, token_info=token_info)
            return self._parse_llm_json(response.text)
        except Exception as e:
            log_llm_event("Gemini", f"Error: {e}", details=str(e))
            logger.error(f"Gemini 호출 실패: {e}")
            return None

    # ==========================================
    # Helper: Retry Logic
    # ==========================================
    def _fetch_with_retry(self, url: str, headers: dict = None, timeout: int = 10, max_retries: int = 3):
        if not headers:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        for attempt in range(max_retries):
            try:
                res = requests.get(url, headers=headers, timeout=timeout)
                if res.status_code == 200:
                    return res
            except requests.exceptions.RequestException as e:
                logger.warning(f"⚠️ {attempt + 1}번째 시도 실패: {url} -> {e}")
                time.sleep(2)
        return None

    # ==========================================
    # Crawl Graph Nodes
    # ==========================================
    # ==========================================
    # Crawl Graph Nodes (Deprecated - Use ScoutAgent instead)
    # ==========================================
    def node_clean_old_data(self, state: CrawlState) -> dict:
        log_llm_event("cleanup", "오래된 데이터 정리 노드 시작")
        deleted_count = self.repo.delete_old_articles(days=30)
        msg = f"과거 데이터 삭제 완료: {deleted_count}건"
        return {"messages": [msg]}
    # ==========================================
    # Comparison Graph Nodes (Agent 1 & 2)
    # ==========================================
    def node_fetch_comparison_data(self, state: ComparisonState) -> dict:
        """
        [Node] 이슈 ID에 해당하는 기사 목록을 가져옵니다.
        """
        issue_id = state.get("issue_id")
        log_llm_event("fetch_comparison", f"이슈 ID {issue_id} 기사 데이터 로드 시작")
        
        articles = self.repo.get_articles_by_issue(issue_id)
        data = []
        for a in articles:
            content = a.body.raw_content if hasattr(a, 'body') and a.body else ""
            data.append({
                'article_id': a.id,
                'press': a.publisher.name if a.publisher else "알수없음",
                'title': a.title,
                'content': content,
                'link': a.url
            })
            
        msg = f"기사 {len(data)}건 로드 완료"
        log_llm_event("fetch_comparison", msg)
        return {"articles": data, "messages": [msg]}

    def node_agent_extractor(self, state: ComparisonState) -> dict:
        """
        [Node / Agent 1] 기사 원문에서 주장과 근거문장 추출하여 JSON 형식으로 변환하여 DB에 저장합니다.
        반환예시
        {
            "publisher": "언론사명",
            "claim": "주장",
            "evidence": "근거문장",
            "link": "기사링크"
        }
        """
        articles = state.get("articles", [])
        issue_id = state.get("issue_id")
        log_llm_event("agent_extractor", f"에이전트 1: {len(articles)}개 기사 주장 추출 및 저장 시작")
        
        extracted_claims = []
        for art in articles:
            prompt = f"""
            다음 뉴스 기사에서 핵심 주장과 그 근거를 추출하여 JSON 형식으로 반환해주세요.
            
            언론사: {art['press']}
            제목: {art['title']}
            내용: {art['content'][:2000]}
            
            [반환 형식 (순수 JSON만)]
            {{
                "publisher": "{art['press']}",
                "claim": "기사의 핵심 주장 (1문장)",
                "evidence": "핵심 주장을 뒷받침하는 기사 내 구체적인 문장",
                "link": "{art['link']}"
            }}
            """
            
            try:
                if state.get("llm_mode") == "gemini_only":
                    # 제미나이 2.0 모델은 JSON Schema를 통한 강력한 형식 고정을 지원합니다.
                    response_schema = {
                        "type": "OBJECT",
                        "properties": {
                            "publisher": {"type": "STRING"},
                            "claim": {"type": "STRING"},
                            "evidence": {"type": "STRING"},
                            "link": {"type": "STRING"}
                        },
                        "required": ["publisher", "claim", "evidence", "link"]
                    }
                    gen_model = genai.GenerativeModel(
                        model_name='gemini-2.0-flash',
                        generation_config={
                            "response_mime_type": "application/json",
                            "response_schema": response_schema
                        }
                    )
                    response = gen_model.generate_content(prompt)
                    final_text = response.text
                else:
                    # 로컬 LLM의 경우 OpenAI 호환 response_format 사용 시도
                    final_text = self._call_local_llm("7B_1", prompt, json_mode=True)
                
                # JSON 파싱
                claim_data = self._parse_llm_json(final_text)
                if claim_data:
                    # ArticleService를 통한 저장 대행
                    self.article_service.save_article_claim(
                        issue_id=issue_id,
                        article_id=art['article_id'],
                        press=claim_data.get('publisher', art['press']),
                        claim=claim_data.get('claim', ''),
                        evidence=claim_data.get('evidence', '')
                    )
                    extracted_claims.append(claim_data)
            except Exception as e:
                logger.error(f"주장 추출 및 저장 실패 ({art['press']}): {e}")
        
        msg = f"총 {len(extracted_claims)}개의 주장 데이터 추출 및 서비스 레이어 저장 완료"
        log_llm_event("agent_extractor", msg)
        return {"extracted_claims": extracted_claims, "messages": [msg]}

    def node_agent_analyzer(self, state: ComparisonState) -> dict:
        """
        [Node / Agent 2] 서비스 레이어를 통해 추출된 주장 데이터를 불러와 다각도 비평 보고서를 생성합니다.
        """
        issue_id = state.get("issue_id")
        log_llm_event("agent_analyzer", f"에이전트 2: 이슈 ID {issue_id} 서비스 레이어 기반 비평 보고서 생성 시작")
        
        # ArticleService를 통해 DB에서 데이터 로드
        db_claims = self.article_service.get_claims_by_issue(issue_id)
        if not db_claims:
            return {"final_analysis": "추출된 주장 데이터가 없어 분석을 진행할 수 없습니다.", "messages": ["분석 데이터 부재"]}
            
        claims_list = [
            {
                "publisher": c.press,
                "claim": c.claim,
                "evidence": c.evidence
            } for c in db_claims
        ]
        
        claims_json = json.dumps(claims_list, ensure_ascii=False, indent=2)
        
        prompt = f"""
        다음은 동일한 이슈에 대한 여러 언론사의 주장 데이터입니다.
        이를 바탕으로 쟁점별 비교 비평 보고서를 작성해주세요.
        
        [데이터 목록]
        {claims_json}
        
        [작성 형식]
        1. 첫 줄에 이슈에 대한 한 줄 총평을 작성하십시오.
        2. 주요 쟁점별로 소제목을 달고, 각 언론사의 입장을 비교하여 서술하십시오.
        3. 마크다운 형식을 사용하여 가독성 있게 작성하십시오.
        4. 예시 구조:
        
        ### 쟁점1: [쟁점 내용]
        - **매체A**: [입장 요약]
        - **매체B**: [입장 요약]
        - **매체C**: [입장 요약]
        
        ...
        """
        
        try:
            if state.get("llm_mode") == "gemini_only":
                gen_model = genai.GenerativeModel('gemini-2.0-flash')
                response = gen_model.generate_content(prompt)
                final_text = response.text
            else:
                final_text = self._call_local_llm("7B_2", prompt)
                
            log_llm_event("agent_analyzer", "비평 보고서 생성 완료")
            return {"final_analysis": final_text, "messages": ["비교 비평 보고서 생성 완료"]}
        except Exception as e:
            msg = f"비평 보고서 생성 실패: {e}"
            log_llm_event("agent_analyzer", msg, type="ERROR")
            return {"final_analysis": "보고서 생성 중 오류가 발생했습니다.", "messages": [msg]}
