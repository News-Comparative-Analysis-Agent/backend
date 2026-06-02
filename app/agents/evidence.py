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
        
        # 이전 시도의 피드백이 있으면 프롬프트에 추가
        feedback_section = ""
        redo_instruction = state.get("judge_feedback", "")
        if redo_instruction:
            feedback_section = f"""
        [이전 시도의 피드백 (반드시 반영할 것)]
        {redo_instruction}
        """

        article_mode = state.get("article_mode", "editorial")
        if article_mode == "politics":
            prompt = f"""
        당신은 정치적 사건 및 현안을 독자에게 객관적이고 사실 위주로 설명·전달하기 위한 기사 원문 문장 추출 전문가입니다.
        아래 [뉴스 원문]에서 정치적 이슈 및 각 주체의 주장·반응을 독자에게 명확하게 알리는 데 사용할 수 있는 문단을 추출하세요.

        {feedback_section}
        [뉴스 원문]
        언론사: {art['press']}
        발행일: {art['published_at']}
        제목: {art['title']}
        내용: {art['content'][:2500]}
        
        [추출 원칙]
        이 뉴스 기사에서 보도하고 있는 핵심 정치적 사건의 팩트(일어난 일)와, 이에 대한 각 주체(정치인, 정당, 대변인 등)의 구체적인 발언 및 공식 입장을 있는 그대로 찾아라.
        기자가 독자에게 이 이슈의 전말과 각 주체의 대립각을 객관적이고 공평하게 전달하기 위해 직접 인용할 수 있는 문단들이어야 한다.
        만약 위에 [이전 시도의 피드백]이 있다면, 해당 내용을 최우선으로 반영하여 문장을 선별하라.

        [claim 추출 규칙]
        - 이 기사가 전달하는 핵심 사건 또는 가장 중요하게 다뤄지는 인물의 핵심 지적/주장 1문장을 원문 그대로 가져온다.
        - 단 한 글자도 바꾸지 마라.

        [evidence 추출 규칙]

        1. evidence를 반드시 두 필드로 분리하여 추출한다.

        evidence_front (핵심 사건의 발생 및 팩트 문단):
        → 이슈를 전달하기 위해 필수적인 구체적 사건 경위, 고발/테러 모의 등의 정황 및 관계 기관(경찰 등)의 조치를 담은 팩트 문단을 통째로 가져온다.
        → 문단 내 문장을 선별하거나 생략하지 마라. 문단 전체를 그대로 가져온다.

        evidence_back (이에 대한 다른 주체/진영의 반응 및 주장 문단):
        → 핵심 사건에 대해 여야 정치인이나 상대 진영이 내놓은 지적, 비판, 대응 주장, 요구 등이 담긴 핵심 문단을 통째로 가져온다.
        → evidence_front와 중복되지 않고, 대립 구도나 이슈의 본질을 균형 있게 보여주는 문단이어야 한다.

        2. 단 한 글자도 바꾸지 마라. 요약·합치기·표현 변형은 절대 금지한다.

        [출력 JSON 예시]
        {{
            "claim": "장동혁 국민의힘 대표는 SNS에서 벌어진 정청래 더불어민주당 대표에 대한 집단적 테러 모의 정황을 두고 '정청래 암살단의 실상은 명청대전의 결과물인 모양'이라고 17일 지적했다.",
            "evidence_front": "앞서 민주당은 이날 오전 기자회견을 열고 '6·3 지방선거 공식 선거운동 기간을 고작 나흘 앞둔 상황에서 정청래를 죽이자 정청래 암살단 모집 등 실체를 알 수 없는 SNS 단체방에서 집단적인 테러 모의가 이뤄지고 있다는 제보가 잇따라 접수되고 있다'며 우려를 표한 바 있다. 이에 경찰은 당초 21일 공식 선거운동 기간 시작에 맞춰 주요 정당 대표 등에 대한 신변보호에 나설 계획을 수정해 신변보호 시기를 앞당기기로 했다.",
            "evidence_back": "장 대표는 이날 자신의 페이스북에 글을 올려 '이재명의 뜻을 거역했다고 암살이라니 무섭다'면서 '이재명 주변의 수많은 죽음들이 떠오른다'며 이같이 밝혔다. 그는 '참담하고 마음이 아프고 괴롭다는 정청래의 심정도 이해가 간다. 이렇게까지 해야 하나 싶기도 할 것 같다'면서 '여당 대표 암살 모의는 결코 가볍게 넘길 문제가 아니다. 범인이 친명이라고 봐줘서도 안된다'고 촉구했다."
        }}
        """



        else:
            prompt = f"""
        당신은 미디어 비평 기사 작성을 위한 원문 문장 추출 전문가입니다.
        아래 [뉴스 원문]에서 기사 작성에 그대로 사용할 수 있는 문단을 추출하세요.
        추출한 문장은 기사에서 다음과 같이 사용됩니다:
        → "[{art['press']}]는 {art['published_at']} 사설 <{art['title']}>에서 '...'라며 '...'라고 했다."
        {feedback_section}
        [뉴스 원문]
        언론사: {art['press']}
        발행일: {art['published_at']}
        제목: {art['title']}
        내용: {art['content'][:2500]}
        
        [추출 원칙]
        이 언론사가 이 사설에서 말하고자 하는 핵심 주장과 근거가 담긴 문단을 찾아라.
        미디어스 기자가 해당 언론사의 입장을 독자에게 전달할 때 직접 인용할 수 있는 문장들이어야 한다.
        만약 위에 [이전 시도의 피드백]이 있다면, 해당 내용을 최우선으로 반영하여 문장을 선별하라.

        [claim 추출 규칙]
        - 이 언론사가 가장 강조하는 핵심 주장 1문장을 원문 그대로 가져온다.
        - 기사에서 가장 선명하게 입장이 드러나는 문장 1개를 그대로 복사한다.
        - 단 한 글자도 바꾸지 마라.

        [evidence 추출 규칙]

        1. evidence를 반드시 두 필드로 분리하여 추출한다.

        evidence_front (판단·해석·문제 제기 문단):
        → 언론사의 판단, 해석, 문제 제기가 담긴 문단을 통째로 가져온다.
        → 문단 내 문장을 선별하거나 생략하지 마라. 문단 전체를 그대로 가져온다.
        → 맥락 유지를 위해 해당 문단 앞뒤의 연결 문장도 포함한다.

        evidence_back (결론·요구·주장 문단):
        → 언론사의 결론, 요구, 주장이 담긴 문단을 통째로 가져온다.
        → evidence_front와 내용이 겹치지 않아야 한다.
        → 별도 결론 문단이 없으면 evidence_front의 마지막 문장들로 채운다.

        2. 단 한 글자도 바꾸지 마라. 요약·합치기·표현 변형은 절대 금지한다.

        [출력 JSON 예시]
        {{
            "claim": "정치적 이유가 있는 것 아니냐는 의구심이 생길 수 있다.",
            "evidence_front": "통화 녹취가 이뤄진 것은 이화영씨가 검찰에서 '쌍방울의 이재명 경기지사 방북 비용 대납을 이 지사에게 보고했다'고 진술한 직후다. 이미 이런 진술이 나왔는데 검찰이 이화영씨를 회유할 이유가 무엇인지 의문이다. 특히 그때는 가만있다가 3년이 지나서야 녹취록 일부를 공개한 서 변호사는 지금 민주당 소속으로 청주시장 출마를 준비 중이다. 정치적 이유가 있는 것 아니냐는 의구심이 생길 수 있다.",
            "evidence_back": "이런 의문을 없앨 방법은 간단하다. 녹취록 전문을 공개하면 된다. 그런데 민주당은 '핵심적인 부분들을 조금씩 공개하겠다'고 한다. 민주당은 이 대통령 사건 공소 취소를 추진하고 있다고 한다. 그렇다면 먼저 각종 녹취록 전체를 국민 앞에 공개해야 한다."
        }}
        """
        
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        try:

            response_schema = {
                "type": "OBJECT",
                "properties": {
                    "claim": {"type": "STRING"},
                    "evidence_front": {"type": "STRING"},
                    "evidence_back": {"type": "STRING"}
                },
                "required": ["claim", "evidence_front", "evidence_back"]
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
            future_to_art = {executor.submit(self._extract_single_card, art, issue_id, llm_mode, state): art for art in articles}
            for future in concurrent.futures.as_completed(future_to_art):
                art = future_to_art[future]
                card_data, usage = future.result()
                
                node_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                node_usage["completion_tokens"] += usage.get("completion_tokens", 0)

                if card_data:
                    # [사용자 요청] 핵심 내용이 부재한 경우(빈 문자열)는 유효하지 않은 카드로 간주
                    if not card_data.get("claim") or not (card_data.get("evidence_front") or card_data.get("evidence_back")):
                        logger.warning(f"⚠️ [EvidenceAgent] {card_data.get('press')} 기사의 핵심 내용이 비어있어 유효하지 않은 카드로 간주합니다.")
                        continue
                        
                    claim_cards.append(card_data)
                    media_views.append({
                        "article_id": card_data.get("article_id"),
                        "press": card_data.get("press", ""),
                        "title": card_data.get("title", ""),
                        "published_at": card_data.get("published_at", ""),
                        "claim": card_data.get("claim", ""),
                        "evidence_front": card_data.get("evidence_front", ""),
                        "evidence_back": card_data.get("evidence_back", ""),
                        "url": card_data.get("url", ""),
                        "raw_content": art.get("content", "")
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
                        evidence_front=card.get('evidence_front', ''),
                        evidence_back=card.get('evidence_back', ''),
                        issue_type=state.get("article_mode", "editorial")
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
            raise e # 에러를 상위(Worker)로 전파하여 실패로 처리

        # ✅ [사용자 요청] 모든 언론사의 Evidence가 하나라도 부재라면 실패로 간주
        if len(claim_cards) < len(articles):
            missing_count = len(articles) - len(claim_cards)
            err_msg = f"일부 언론사 Evidence 추출 실패 (입력:{len(articles)}, 성공:{len(claim_cards)}). {missing_count}개 매체 누락으로 인해 분석을 중단합니다."
            logger.error(f"❌ [EvidenceAgent:StrictCheck] {err_msg}")
            raise ValueError(err_msg)
        
        # 전체 상태 업데이트
        total_tokens = update_total_tokens(state, node_usage, "EvidenceAgent")
        
        return {
            "media_views": media_views,
            "messages": [msg],
            "total_tokens": total_tokens,
        }
