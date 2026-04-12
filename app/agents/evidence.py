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
            # 발행일 정보 추가 (YYYY-MM-DD 형식으로 변환)
            pub_date = a.published_at.strftime("%Y-%m-%d") if a.published_at else "날짜미상"
            
            data.append({
                'article_id': a.id,
                'press': a.publisher.name if a.publisher else "알수없음",
                'title': a.title,
                'content': content,
                'url': a.url,
                'published_at': pub_date
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
        당신은 언론의 프레임을 파헤치는 예리한 미디어 분석가입니다. 아래 [뉴스 원문]을 읽고, 해당 언론사가 숨기고 있는 정치적 의도와 핵심 논조를 분석하세요.
        
        [뉴스 원문]
        언론사: {art['press']}
        제목: {art['title']}
        내용: {art['content'][:2500]}
        
        [작성 지침]
        1. 모든 값은 반드시 한국어로만 작성하세요.
        2. "thought": 본문을 읽고, 어느 단락이 이 기사의 핵심 논조를 담고 있는지 분석하는 과정을 2~3문장으로 간략히 적어주세요.
        3. "claim": 기사가 독자에게 심어주려는 '최종적인 정치적 인상'을 1문장으로 기술하세요.
        4. "evidence": 위 주장의 근거가 되는 기사 본문 내 '특정 문장'을 **단 한 글자도 바꾸지 말고, 원문 그대로 100% 똑같이 복사(Ctrl+C, Ctrl+V)** 해서 넣으세요. 본문에 없는 단어를 넣으면 절대 안 됩니다.
        5. "narrative": 이 기사가 사법 이슈를 '법리적 정의'로 보는지, '정치적 수단'으로 보는지 판별하여 그 이유를 기술하세요.

        [출력 JSON 예시]
        {{
            "thought": "해당 기사는 검찰의 진술 회유 의혹이라는 사법적 본질보다 녹취록 공개의 '절차적 미비'와 '정치적 배후'를 부각하고 있습니다. 이는 의혹의 신뢰도를 떨어뜨려 사법 리스크를 정략적 공세로 치환하려는 프레임 전략으로 분석됩니다.",
            "claim": "민주당의 폭로는 선거를 노린 불순한 의도가 담긴 짜깁기이므로 신뢰할 수 없다.",
            "evidence": "서 변호사는 지금 민주당 소속으로 청주시장 출마를 준비 중이다. 정치적 이유가 있는 것 아니냐는 의구심이 생길 수밖에 없다. 이런 의문을 없앨 방법은 간단하다. 녹취록 전문을 공개하면 된다.",
            "narrative": "녹취록의 진실성보다는 공개 의도의 불순함을 강조하며, 사건의 본질을 정치적 공작 프레임으로 전환하여 보도하고 있습니다."
        }}
        """
        
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        try:

            response_schema = {
                "type": "OBJECT",
                "properties": {
                    "thought": {"type": "STRING"},
                    "claim": {"type": "STRING"},
                    "evidence": {"type": "STRING"},
                    "narrative": {"type": "STRING"}
                },
                "required": ["thought", "claim", "evidence", "narrative"]
            }
            
            # call_llm이 내부적으로 llm_mode 판단 후 제미나이/로컬 분기 및 JSON 파싱을 모두 수행함!
            card_data, usage = call_llm(prompt=prompt, model_size="local", state=state, schema=response_schema)
            
            if card_data:
                # 내부 식별용 및 메타데이터 자동 병합
                card_data['article_id'] = art['article_id']
                card_data['url'] = art['url']
                card_data['press'] = art['press']
                card_data['published_at'] = art.get('published_at')
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
        workers = 5 if llm_mode == "gemini_only" else 1 # TODO 몇개까지 버티는지 테스트 진행예정
        
        msg_start = f"Agent 1 (Evidence): {len(articles)}개 기사 병렬 주장 카드 추출 시작 (Mode: {llm_mode})"
        logger.info(f"🔍 [EvidenceAgent:Extract] {msg_start}")
        log_llm_event("agent_evidence", msg_start)
        
        claim_cards = [] # DB 저장 및 텍스트 로깅용
        media_views = [] # State 전달용 (Flat 구조)
        node_usage = {"prompt_tokens": 0, "completion_tokens": 0}

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(self._extract_single_card, art, issue_id, llm_mode, state) for art in articles]
            for future in concurrent.futures.as_completed(futures):
                card_data, usage = future.result()
                
                node_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                node_usage["completion_tokens"] += usage.get("completion_tokens", 0)

                if card_data:
                    claim_cards.append(card_data)
                    media_views.append({
                        "press": card_data.get("press", ""),
                        "published_at": card_data.get("published_at", ""),
                        "thought": card_data.get("thought", ""),
                        "narrative": card_data.get("narrative", ""),
                        "claim": card_data.get("claim", ""),
                        "evidence": card_data.get("evidence", ""),
                        "url": card_data.get("url", "")
                    })
                    
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
            "media_views": media_views,
            "messages": [msg],
            "total_tokens": total_tokens,
        }
