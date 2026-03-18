import json
from sqlalchemy.orm import Session

import google.generativeai as genai
from app.agents.state import ReviewState
from app.core.logger import logger

class ReviewAgent:
    """
    Agent) Review Agent (최종 품질 검토)
    • 입력: issue_id + user_content (사용자 수정본)
    • 출력:
      - 신뢰도 분석: 유사도 점수 + 소스 기사 3건 (제목/URL/언론사)
      - 가이드라인 검증: 차별 표현/자극적 형용사/낙인화/미확인 사실 등 4개 항목
      - AI 종합 의견: 편집장 관점의 종합 평가 2~3문장
    """
    def __init__(self, db: Session = None):
        self.db = db

    # -----------------------------------------------------------
    # Node 1: 이슈 정보 + 기사 메타(제목/URL/언론사) 로드
    # -----------------------------------------------------------
    def node_fetch_articles(self, state: ReviewState) -> dict:
        """
        [Node 1] DB에서 이슈 정보 및 관련 기사의 메타 정보를 가져옵니다.
        """
        issue_id = state.get("issue_id")
        logger.info(f"🔍 [ReviewAgent] Node1: 이슈({issue_id}) 기사 메타 로드 시작")

        try:
            from app.domains.drafts.repository import DraftRepository
            repo = DraftRepository(self.db)

            issue = repo.get_issue_by_id(issue_id)
            if not issue:
                return {"error": f"이슈 ID {issue_id}를 찾을 수 없습니다.", "messages": ["이슈 없음 - 검토 중단"]}

            articles = repo.get_articles_meta_by_issue(issue_id)
            articles_meta = []
            for art in articles:
                pub_name = art.publisher.name if getattr(art, "publisher", None) else "알 수 없음"
                articles_meta.append({
                    "title": art.title,
                    "url": art.url,
                    "publisher": pub_name,
                    "published_at": art.published_at.strftime("%Y-%m-%dT%H:%M") if art.published_at else ""
                })

            logger.info(f"🔍 [ReviewAgent] Node1: 이슈 '{issue.name}', 기사 {len(articles_meta)}건 로드 완료")
            return {
                "issue_name": issue.name,
                "issue_description": issue.description or "",
                "articles_meta": articles_meta,
                "messages": [f"기사 {len(articles_meta)}건 로드 완료"]
            }

        except Exception as e:
            msg = f"기사 로드 실패: {e}"
            logger.error(f"🔍 [ReviewAgent] {msg}")
            return {"error": msg, "messages": [msg]}

    # -----------------------------------------------------------
    # Node 2: 신뢰도 분석 (소스 기사 추출)
    # -----------------------------------------------------------
    def node_calculate_reliability(self, state: ReviewState) -> dict:
        """
        [Node 2] 유사도 계산을 생략하고, 이슈에 속한 모든 기사 정보를 소스로 반환합니다.
        """
        articles_meta = state.get("articles_meta", [])
        logger.info(f"📊 [ReviewAgent] Node2: 소스 기사 추출 시작 (총 {len(articles_meta)}건)")

        # 모든 기사 정보를 소스로 사용
        top_sources = articles_meta
        
        # 유사도 점수는 더 이상 계산하지 않으므로 기본값(0) 처리
        reliability_score = 0
        risk_level = "안전"

        logger.info(f"📊 [ReviewAgent] Node2: 소스 기사 {len(top_sources)}건 추출 완료")
        return {
            "reliability_score": reliability_score,
            "risk_level": risk_level,
            "top_sources": top_sources,
            "messages": [f"전체 소스 기사 {len(top_sources)}건 추출 완료"]
        }



    # -----------------------------------------------------------
    # Node 3: 가이드라인 검증 + AI 종합 의견 (Gemini/Local LLM)
    # -----------------------------------------------------------
    def node_analyze_and_opine(self, state: ReviewState) -> dict:
        """
        [Node 3] Gemini 또는 로컬 LLM을 사용하여 가이드라인 검증과 AI 종합 의견을 동시에 생성합니다.
        """
        from app.agents.utils import call_llm, update_total_tokens
        
        user_content = state.get("user_content", "")
        issue_name = state.get("issue_name", "")
        issue_description = state.get("issue_description", "")
        logger.info(f"⚖️ [ReviewAgent] Node3: 가이드라인 검증 + 종합 의견 생성 시작")

        GUIDELINE_LABELS = [
            "혐오 표현 및 차별적 서술",
            "자극적인 형용사 사용",
            "특정 집단 비하 또는 낙인화 표현",
            "미확인 사실 및 추측성 서술",
        ]

        prompt = f"""
당신은 언론 윤리 전문가이자 편집장입니다.
아래 기자가 작성한 최종 기사를 엄격히 검토하십시오.

[검토 대상 기사]
{user_content}

[이슈 정보]
이슈명: {issue_name}
이슈 배경: {issue_description or "정보 없음"}

[가이드라인 검증 항목 - 4가지 각각 검사]
1. 혐오 표현 및 차별적 서술 - 특정 인종·성별·종교·지역 비하 표현이 있는가?
2. 자극적인 형용사 사용 - '전격', '충격', '폭탄', '파국' 등 선정적 표현이 있는가?
3. 특정 집단 비하 또는 낙인화 표현 - 특정 정치 세력·사회집단을 일방적으로 낙인 찍는 표현이 있는가?
4. 미확인 사실 및 추측성 서술 - 검증되지 않은 사실을 단정적으로 기술하는 표현이 있는가?

[종합 의견]
위 기사의 전반적인 완성도, 균형성, 언론 윤리 준수 여부에 대한 종합 의견을 2~3문장으로 작성하십시오.

[출력 형식 - 반드시 순수 JSON만 반환]
{{
  "guideline_checks": [
    {{"label": "혐오 표현 및 차별적 서술", "passed": true, "detail": ""}},
    {{"label": "자극적인 형용사 사용", "passed": false, "detail": "'전격 중단' 표현 감지"}},
    {{"label": "특정 집단 비하 또는 낙인화 표현", "passed": true, "detail": ""}},
    {{"label": "미확인 사실 및 추측성 서술", "passed": true, "detail": ""}}
  ],
  "ai_opinion": "종합 평가 2~3문장"
}}
        """

        response_schema = {
            "type": "OBJECT",
            "properties": {
                "guideline_checks": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "label": {"type": "STRING"},
                            "passed": {"type": "BOOLEAN"},
                            "detail": {"type": "STRING"}
                        },
                        "required": ["label", "passed", "detail"]
                    }
                },
                "ai_opinion": {"type": "STRING"}
            },
            "required": ["guideline_checks", "ai_opinion"]
        }

        try:
            # utils.call_llm을 사용하여 llm_mode에 따라 호출
            result, usage = call_llm(prompt, "7B_1", state, schema=response_schema)
            
            # 토큰 업데이트
            total_tokens = update_total_tokens(state, usage)

            if not result:
                raise ValueError("LLM 응답 결과과 비어있습니다.")

            logger.info(f"⚖️ [ReviewAgent] Node3: LLM 분석 완료")

        except Exception as e:
            msg = f"LLM 분석 오류: {e}"
            logger.error(f"⚖️ [ReviewAgent] {msg}")
            result = {
                "guideline_checks": [
                    {"label": lbl, "passed": True, "detail": ""} for lbl in GUIDELINE_LABELS
                ],
                "ai_opinion": f"AI 분석 중 오류가 발생했습니다: {str(e)}"
            }
            total_tokens = state.get("total_tokens", {"prompt_tokens": 0, "completion_tokens": 0})

        return {
            "guideline_checks": result.get("guideline_checks", []),
            "ai_opinion": result.get("ai_opinion", ""),
            "total_tokens": total_tokens,
            "messages": ["가이드라인 검증 및 종합 의견 생성 완료"]
        }

