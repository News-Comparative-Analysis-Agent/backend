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

    def _build_issue_payload_item(self, issue_id: int, card: dict) -> dict:
        """IssueAgent 전달용 표준 JSON 아이템을 생성합니다."""
        return {
            "media_views": [
                {
                    "press": card.get("press", ""),
                    "claim": card.get("claim", ""),
                    "evidence": card.get("evidence", ""),
                    "url": card.get("url", "")
                }
            ]
        }

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
        당신은 예리한 사실 기반 팩트체커입니다. 아래 주어진 [뉴스 원문]을 읽고, 해당 언론사가 가장 강하게 내세우는 핵심 주장을 발췌하세요.
        
        [뉴스 원문]
        언론사: {art['press']}
        제목: {art['title']}
        내용: {art['content'][:2500]}
        
        [작성 지침]
        1. 모든 값은 반드시 한국어로만 작성하세요.
        2. "thought": 본문을 읽고, 어느 단락이 이 기사의 핵심 논조를 담고 있는지 분석하는 과정을 2~3문장으로 간략히 적어주세요.
        3. "claim": 본문의 핵심 주장(기사 작성자의 요점)을 1문장으로 요약하세요.
        4. "evidence": 위 주장의 근거가 되는 기사 본문 내 '특정 문장'을 **단 한 글자도 바꾸지 말고, 원문 그대로 100% 똑같이 복사(Ctrl+C, Ctrl+V)** 해서 넣으세요. 본문에 없는 단어를 넣으면 절대 안 됩니다.
        
        [출력 JSON 예시]
        {{
            "thought": "이 기사는 세 번째 단락에서 의대 증원의 부작용을 강도 높게 비판하고 있다. 따라서 해당 부분을 핵심 주장과 인용 근거로 삼는 것이 적절하다.",
            "claim": "정부의 의대 증원 정책은 의료 현장의 목소리를 배제한 강압적인 정책이다.",
            "evidence": "대한의사협회는 정부가 의료계와 충분한 사전 협의 없이 2,000명 증원을 일방적으로 통보했다고 강력히 비판했다."
        }}
        """
        
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        try:

            response_schema = {
                "type": "OBJECT",
                "properties": {
                    "thought": {"type": "STRING"},
                    "claim": {"type": "STRING"},
                    "evidence": {"type": "STRING"}
                },
                "required": ["thought", "claim", "evidence"]
            }
            
            # call_llm이 내부적으로 llm_mode 판단 후 제미나이/로컬 분기 및 JSON 파싱을 모두 수행함!
            card_data, usage = call_llm(prompt=prompt, model_size="local", state=state, schema=response_schema)
            
            if card_data:
                # 내부 식별용 및 메타데이터 자동 병합
                card_data['article_id'] = art['article_id']
                card_data['url'] = art['url']
                card_data['press'] = art['press']
                return card_data, usage
        except Exception as e:
            logger.error(f"주장 카드 추출 실패 ({art['press']}): {e}")
            
        return None, usage

    @traceable(name="Agent 1: Evidence (주장 및 근거 추출) 🕵️‍♂️")
    def node_extract_claims(self, state: ComparisonState) -> dict:
        """
        [Node] 기사에서 주장 카드(Claim Card)를 추출합니다.
        """
        articles = state.get("articles", [])
        issue_id = state.get("issue_id")
        llm_mode = state.get("llm_mode", "local_only")
        
        if not articles:
            return {"messages": ["로드된 기사가 없습니다."]}
            
        # VRAM 보호를 위해 LLM 모드별 워커 수 동적 할당
        # Gemini는 외부 API이므로 빠르게 5개, 로컬 7B는 OOM 방지를 위해 1~2개로 제한
        workers = 5 if llm_mode == "gemini_only" else 2 # TODO 몇개까지 버티는지 테스트 진행예정
        
        msg_start = f"Agent 1 (Evidence): {len(articles)}개 기사 병렬 주장 카드 추출 시작 (Mode: {llm_mode})"
        logger.info(f"🔍 [EvidenceAgent:Extract] {msg_start}")
        log_llm_event("agent_evidence", msg_start)
        
        claim_cards = []
        issue_payload_items = []
        node_usage = {"prompt_tokens": 0, "completion_tokens": 0}

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(self._extract_single_card, art, issue_id, llm_mode, state) for art in articles]
            for future in concurrent.futures.as_completed(futures):
                card_data, usage = future.result()
                
                node_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                node_usage["completion_tokens"] += usage.get("completion_tokens", 0)

                if card_data:
                    claim_cards.append(card_data)
                    issue_payload_items.append(self._build_issue_payload_item(issue_id, card_data))
                    
        # DB 저장
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
                    saved_claims_count += 1
                except Exception as e:
                    logger.error(f"Claim 저장 중 DB 에러: {e}")
                
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
        
        return {
            "issue_payload_items": issue_payload_items,
            "messages": [msg],
            "total_tokens": total_tokens,
        }
