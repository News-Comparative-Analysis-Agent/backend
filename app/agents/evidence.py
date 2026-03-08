import json
import concurrent.futures
from typing import Dict, Any, List
import google.generativeai as genai
from sqlalchemy.orm import Session

from app.agents.state import ComparisonState
from app.agents.utils import call_local_llm, parse_llm_json
from app.core.logger import logger, log_llm_event
from app.domains.articles.service import ArticleService
from app.scroller.repository import ScrollerRepository

class EvidenceAgent:
    """
    Agent 1) Evidence Agent (주장·근거 추출)
    • 입력: 동일 이슈 기사 3~7개 원문
    • 출력(JSON): 매체별 주장 카드
      o 주장 1문장
      o 원문 인용(근거)
      o 기사 URL/매체
    """
    def __init__(self, db: Session):
        self.db = db
        self.repo = ScrollerRepository(db)
        self.article_service = ArticleService(db)

    def node_fetch_articles(self, state: ComparisonState) -> dict:
        """[Node] DB에서 이슈 ID에 속한 기사 원문을 가져옵니다."""
        issue_id = state.get("issue_id")
        log_llm_event("agent_evidence", f"이슈 ID {issue_id} 기사 데이터 로드 시작")
        
        articles = self.repo.get_articles_by_issue(issue_id)
        data = []
        for a in articles:
            content = a.body.raw_content if hasattr(a, 'body') and a.body else ""
            data.append({
                'article_id': a.id,
                'press': a.publisher.name if a.publisher else "알수없음",
                'title': a.title,
                'content': content,
                'url': a.url
            })
            
        msg = f"기사 {len(data)}건 로드 완료"
        log_llm_event("agent_evidence", msg)
        return {"articles": data, "messages": [msg]}

    def _extract_single_card(self, art: dict, issue_id: int, llm_mode: str) -> dict:
        
        prompt = f"""
        당신은 사실 기반 팩트체커입니다. 아래 뉴스 기사 본문에서 핵심 주장을 발췌하여 JSON 주장 카드를 생성하세요.
        
        [뉴스 원문]
        언론사: {art['press']}
        제목: {art['title']}
        내용: {art['content'][:2500]}
        
        [지시사항]
        1. "claim": 기사가 전달하려는 가장 핵심적인 주장 1문장.
        2. "evidence": 위 주장을 뒷받침하는 기사 내부의 '정확한 원문 인용구' (작성자가 지어내지 말 것).
        3. "url": 제공된 기사 URL.
        4. "press": 제공된 언론사명.
        
        [반환 형식 - 순수 JSON만]
        {{
            "claim": "핵심 주장 1문장",
            "evidence": "원문 인용(근거)",
            "url": "{art['url']}",
            "press": "{art['press']}"
        }}
        """
        
        try:
            if llm_mode == "gemini_only":
                response_schema = {
                    "type": "OBJECT",
                    "properties": {
                        "claim": {"type": "STRING"},
                        "evidence": {"type": "STRING"},
                        "url": {"type": "STRING"},
                        "press": {"type": "STRING"}
                    },
                    "required": ["claim", "evidence", "url", "press"]
                }
                gen_model = genai.GenerativeModel('gemini-2.0-flash', generation_config={"response_mime_type": "application/json", "response_schema": response_schema})
                response = gen_model.generate_content(prompt)
                # Gemini 2.0 모델은 Structured Outputs를 통해 완벽한 JSON을 보장하므로 정규식 파서 불필요
                card_data = json.loads(response.text)
            else:
                final_text = call_local_llm("7B_1", prompt, json_mode=True)
                # 로컬 모델은 불필요한 마크다운 백틱 등을 포함할 수 있어 파싱 헬퍼 필수
                card_data = parse_llm_json(final_text)
            
            if card_data:
                # 내부 식별용 매핑 (리스트 취합 후 메인 스레드에서 일괄 저장 용도)
                card_data['article_id'] = art['article_id'] 
                return card_data
        except Exception as e:
            logger.error(f"주장 추출 실패 ({art['press']}): {e}")
            
        return None

    def node_extract_claims(self, state: ComparisonState) -> dict:
        """
        [Node] 병렬 처리를 통해 여러 기사에서 주장 카드(Claim Card)를 동시 추출합니다.
        """
        articles = state.get("articles", [])
        issue_id = state.get("issue_id")
        llm_mode = state.get("llm_mode", "gemini_only")
        
        if not articles:
            return {"claim_cards": [], "messages": ["로드된 기사가 없습니다."]}
            
        # VRAM 보호를 위해 LLM 모드별 워커 수 동적 할당
        # Gemini는 외부 API이므로 빠르게 5개, 로컬 7B는 OOM 방지를 위해 1~2개로 제한
        workers = 5 if llm_mode == "gemini_only" else 2
        
        log_llm_event("agent_evidence", f"Agent 1 (Evidence): {len(articles)}개 기사 병렬 추출 시작 (Workers: {workers})")
        
        claim_cards = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(self._extract_single_card, art, issue_id, llm_mode) for art in articles]
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res:
                    claim_cards.append(res)
                    
        # 스레드가 모두 종료된 후 메인 스레드에서 일괄 데이터베이스 저장 (Thread-Safety 보장)
        saved_claims_count = 0
        for card in claim_cards:
            try:
                # 딕셔너리에서 원본 press 정보를 가져오고, 없으면 fallback
                target_press = card.get('press', '알수없음')
                self.article_service.save_article_claim(
                    issue_id=issue_id,
                    article_id=card['article_id'],
                    press=target_press,
                    claim=card.get('claim', ''),
                    evidence=card.get('evidence', '')
                )
                saved_claims_count += 1
            except Exception as e:
                logger.error(f"Claim 일괄 저장 중 DB 에러: {e}")
                
        # 변경 사항 커밋
        try:
            self.db.commit()
            msg = f"총 {len(claim_cards)}개의 주장 카드 생성 완료 및 DB 저장 완료 ({saved_claims_count}건)"
        except Exception as e:
            self.db.rollback()
            msg = f"총 {len(claim_cards)}개의 주장 카드 생성 완료했으나, DB 저장 실패: {e}"
            logger.error(msg)
            
        log_llm_event("agent_evidence", msg)
        return {"claim_cards": claim_cards, "messages": [msg]}
