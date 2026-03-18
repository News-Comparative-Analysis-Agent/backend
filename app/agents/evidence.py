import json
import concurrent.futures
from typing import Dict, Any, List
import google.generativeai as genai
from sqlalchemy.orm import Session
from langsmith import traceable

from app.agents.state import ComparisonState
from app.agents.utils import call_llm, update_total_tokens
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
            
        msg = f"이슈 ID {issue_id}에 대해 기사 {len(data)}건 로드 완료"
        logger.info(f"🔍 [EvidenceAgent:Fetch] {msg}")
        
        # 기사 정보 로깅 추가
        if data:
            logger.info(f"🔍 [EvidenceAgent:Fetch] 분석 대상 기사 리스트:")
            for i, d in enumerate(data, 1):
                logger.info(f"   {i}. [{d['press']}] {d['title']}")
                
        return {"articles": data, "messages": [msg]}

    def _extract_single_card(self, art: dict, issue_id: int, llm_mode: str, state: ComparisonState) -> tuple[dict | None, dict]:
        
        prompt = f"""
        당신은 사실 기반 팩트체커입니다. 아래 뉴스 기사 본문에서 핵심 주장을 발췌하여 원자적(Atomic) 주장 카드를 생성하세요.
        
        [뉴스 원문]
        언론사: {art['press']}
        제목: {art['title']}
        내용: {art['content'][:2500]}
        
        [지시사항]
        1. "claim": 기사가 전달하려는 가장 핵심적인 주장 1문장.
        2. "evidence": 위 주장을 뒷받침하는 기사 내부의 '정확한 원문 인용구' (작성자가 지어내지 말 것).
        3. "summary": 해당 기사 전체 내용을 1~2문장으로 간결하게 요약한 문장.
        4. "url": 제공된 기사 URL ({art['url']}).
        5. "press": 제공된 언론사명 ({art['press']}).
        
        [반환 형식 - 순수 JSON만]
        {{
            "claim": "핵심 주장 1문장",
            "evidence": "원문 인용(근거)",
            "summary": "기사 전체 요약 1~2문장",
            "url": "{art['url']}",
            "press": "{art['press']}"
        }}
        """
        
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        try:
            if llm_mode == "gemini_only":
                response_schema = {
                    "type": "OBJECT",
                    "properties": {
                        "claim": {"type": "STRING"},
                        "evidence": {"type": "STRING"},
                        "summary": {"type": "STRING"},
                        "url": {"type": "STRING"},
                        "press": {"type": "STRING"}
                    },
                    "required": ["claim", "evidence", "summary", "url", "press"]
                }
                gen_model = genai.GenerativeModel('gemini-2.0-flash', generation_config={"response_mime_type": "application/json", "response_schema": response_schema})
                response = gen_model.generate_content(prompt)
                card_data = json.loads(response.text)
                usage["prompt_tokens"] = len(prompt) // 4
                usage["completion_tokens"] = len(response.text) // 4
            else:
                card_data, usage = call_llm(prompt, "7B", state)
            
            if card_data:
                # 내부 식별용 매핑
                card_data['article_id'] = art['article_id'] 
                return card_data, usage
        except Exception as e:
            logger.error(f"주장 및 요약 추출 실패 ({art['press']}): {e}")
            
        return None, usage

    @traceable(name="Agent 1: Evidence (주장 및 근거 추출) 🕵️‍♂️")
    def node_extract_claims(self, state: ComparisonState) -> dict:
        """
        [Node] 병렬 처리를 통해 여러 기사에서 주장 카드(Claim Card)와 기사 요약을 동시 추출합니다.
        """
        articles = state.get("articles", [])
        issue_id = state.get("issue_id")
        llm_mode = state.get("llm_mode", "gemini_only")
        
        if not articles:
            return {"claim_cards": [], "messages": ["로드된 기사가 없습니다."]}
            
        workers = 5 if llm_mode == "gemini_only" else 2
        
        msg_start = f"Agent 1 (Evidence): {len(articles)}개 기사 병렬 추출 및 요약 시작 (Mode: {llm_mode})"
        logger.info(f"🔍 [EvidenceAgent:Extract] {msg_start}")
        log_llm_event("agent_evidence", msg_start)
        
        claim_cards = []
        node_usage = {"prompt_tokens": 0, "completion_tokens": 0}

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(self._extract_single_card, art, issue_id, llm_mode, state) for art in articles]
            for future in concurrent.futures.as_completed(futures):
                card_data, usage = future.result()
                
                node_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                node_usage["completion_tokens"] += usage.get("completion_tokens", 0)

                if card_data:
                    claim_cards.append(card_data)
                    
        # DB 저장 및 기사 요약 업데이트
        saved_claims_count = 0
        try:
            for card in claim_cards:
                try:
                    # 1. 주장 카드 저장
                    self.article_service.save_article_claim(
                        issue_id=issue_id,
                        article_id=card['article_id'],
                        press=card.get('press', '알수없음'),
                        claim=card.get('claim', ''),
                        evidence=card.get('evidence', '')
                    )
                    # 2. 개별 기사용 요약문 업데이트 (신규 추가)
                    if card.get('summary'):
                        self.repo.update_article_summary(card['article_id'], card['summary'])
                        
                    saved_claims_count += 1
                except Exception as e:
                    logger.error(f"Claim/Summary 저장 중 DB 에러: {e}")
                
            # 7. 기사 카드 로깅 강화
            if claim_cards:
                logger.info(f"🔍 [EvidenceAgent:Extract] 추출된 주장 카드 목록:")
                for i, card in enumerate(claim_cards, 1):
                    logger.info(f"   {i}. [{card.get('press')}] {card.get('claim')[:50]}...")
                    # 상세 내용은 log_llm_event로 남김
                    log_llm_event("agent_evidence", f"Card {i} Details", details=json.dumps(card, ensure_ascii=False, indent=2))
            
            self.db.commit()
            msg = f"총 {len(claim_cards)}개 핵심 주장 카드 추출 완료 및 DB 저장 완료 ({saved_claims_count}건)"
            logger.info(f"🔍 [EvidenceAgent:Extract] {msg}")
        except Exception as e:
            self.db.rollback()
            msg = f"주장 카드 생성 완료({len(claim_cards)}건) 및 DB 저장 실패: {e}"
            logger.error(f"🔍 [EvidenceAgent:Extract] {msg}")
        
        # 전체 상태 업데이트
        total_tokens = update_total_tokens(state, node_usage, "EvidenceAgent")
        
        return {"claim_cards": claim_cards, "messages": [msg], "total_tokens": total_tokens}
