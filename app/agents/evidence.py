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
        당신은 미디어 비평 기사 작성을 위한 원문 문장 추출 전문가입니다.
        아래 [뉴스 원문]에서 기사 작성에 그대로 사용할 수 있는 문장들을 추출하세요.
        추출한 문장은 기사에서 다음과 같이 사용됩니다:
        → "[{art['press']}]는 {art['published_at']} 사설 <{art['title']}>에서 '...'라고 했다."

        [뉴스 원문]
        언론사: {art['press']}
        발행일: {art['published_at']}
        제목: {art['title']}
        내용: {art['content'][:2500]}

        [추출 규칙 - 반드시 따를 것]
        1. **판단 문장 우선 추출**: 기사 본문에서 사건을 단순히 설명하는 문장보다는, 언론사의 '입장, 평가, 가치 판단, 주장'이 담긴 문장을 최우선으로 추출하십시오.
           - 예: "~은 부적절하다", "~해야 한다", "~라는 의구심이 든다" 등 매체의 목소리가 드러나는 문장.
        
        2. **사건 설명 문장 최소화**: 언제, 누가, 무엇을 했는지에 대한 단순 팩트 설명 문장은 꼭 필요한 경우가 아니면 제외하십시오. (이 부분은 ClusterAgent에서 이미 처리됨)

        3. **연속된 맥락 유지**: 추출된 문장들이 매체의 논조를 논리적으로 보여줄 수 있도록 핵심 문장 3~5개를 선정하십시오.

        4. **원문 그대로**: 문장을 요약하거나 수정하지 말고, 기사 본문에 있는 표현을 토씨 하나 틀리지 않게 그대로 가져오십시오.

        [작성 지침]
        1. "claim": 이 언론사가 가장 강조하는 핵심 주장을 원문에서 1문장 그대로 가져온다.
           → 기사에서 가장 선명하게 입장이 드러나는 문장 1개를 그대로 복사한다.

        2. "evidence": 사실관계 문장 2~3개와 언론사 판단·논조 문장 3~4개를 합쳐
        정확히 5~7문장만 원문 그대로 가져온다.
        → 사실관계 우선 선택 기준: 사건 경위, 직접 인용 발언, 수치, 날짜가 포함된 문장
        → 판단·논조 우선 선택 기준: 언론사가 직접 평가하거나 주장하는 문장
        → 단 한 글자도 바꾸지 마라. 요약·합치기·표현 변형은 절대 금지한다.
        → 5문장 미만이거나 8문장 이상이면 규칙 위반이다.
        
        [출력 JSON 예시]
        {{
            "claim": "정치적 이유가 있는 것 아니냐는 의구심이 생길 수밖에 없다.",
            "evidence": "민주당은 29일 국회 기자간담회를 열고 2023년 6월 19일 박 검사와 서민석 변호사의 통화 녹취 일부를 공개했다. 박 검사는 서 변호사에게 '이재명 씨가 완전히 주범이 되고 이 사람이 종범이 되는 식의 자백이 있어야 저희가 그거를 할 수가 있고'라고 말했다. 이 전 부지사는 이 사건으로 징역 7년 8개월이 확정됐고, 이 대통령은 공범으로 기소된 상태다. 그때는 가만있다가 3년이 지나서야 녹취록 일부를 공개한 서 변호사는 지금 민주당 소속으로 청주시장 출마를 준비 중이다. 이런 의문을 없앨 방법은 간단하다. 녹취록 전문을 공개하면 된다. 민주당은 이 대통령 사건 공소 취소를 추진하고 있다고 한다. 그렇다면 먼저 각종 녹취록 전체를 국민 앞에 공개해야 한다."
        }}
        """
        
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        try:

            response_schema = {
                "type": "OBJECT",
                "properties": {
                    "claim": {"type": "STRING"},
                    "evidence": {"type": "STRING"}
                },
                "required": ["claim", "evidence"]
            }
            
            # call_llm이 내부적으로 llm_mode 판단 후 제미나이/로컬 분기 및 JSON 파싱을 모두 수행함!
            card_data, usage = call_llm(prompt=prompt, model_size="local", state=state, schema=response_schema)
            
            if card_data:
                # 내부 식별용 및 메타데이터 자동 병합
                card_data['article_id'] = art['article_id']
                card_data['url'] = art['url']
                card_data['press'] = art['press']
                card_data['title'] = art['title'] 
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
        workers = 1 if llm_mode == "gemini_only" else 1 # TODO 몇개까지 버티는지 테스트 진행예정
        
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
                        "article_id": card_data.get("article_id"),
                        "press": card_data.get("press", ""),
                        "title": card_data.get("title", ""),
                        "published_at": card_data.get("published_at", ""),
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
                        press=card.get('press') or '알수없음',
                        claim=card.get('claim') or '',
                        evidence=card.get('evidence') or ''
                    )
                    saved_claims_count += 1
                except Exception as e:
                    logger.error(f"Claim 저장 중 DB 에러: {e}")
                
            # 7. 기사 카드 로깅 강화
            if claim_cards:
                logger.info(f"🔍 [EvidenceAgent:Extract] 추출된 주장 카드 목록:")
                for i, card in enumerate(claim_cards, 1):
                    claim_text = str(card.get('claim') or "")
                    logger.info(f"   {i}. [{card.get('press')}] {claim_text[:50]}...")
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
