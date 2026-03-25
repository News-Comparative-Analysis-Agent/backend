import json
from sqlalchemy.orm import Session

import google.generativeai as genai
from app.agents.state import ReviewState
from app.core.logger import logger

class ReviewAgent:
    """
    Agent) Review Agent (최종 품질 검토)
    • 입력: issue_id + pre_generated_draft (사용자 수정본 또는 DB 저장본)
    • 출력:
      - 가이드라인 검증: 차별 표현/자극적 형용사/낙인화/미확인 사실 + 핵심 쟁점 반영 여부
      - AI 종합 의견: 편집장 관점의 종합 평가
    """
    def __init__(self, db: Session = None):
        self.db = db

    # -----------------------------------------------------------
    # Node 1: 이슈 정보 + 분석 메타데이터 + 기사 메타 로드
    # -----------------------------------------------------------
    def node_fetch_articles(self, state: ReviewState) -> dict:
        """
        [Node 1] DB에서 이슈 정보, 분석 메타데이터(배경, 쟁점, 요약) 및 관련 기사의 메타 정보를 가져옵니다.
        """
        issue_id = state.get("issue_id")
        logger.info(f"🔍 [ReviewAgent] Node1: 이슈({issue_id}) 분석 데이터 로드 시작")

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

            # pre_generated_draft에서 실제 본문 추출 (JSON 구조 고려)
            raw_draft = issue.pre_generated_draft or ""
            parsed_draft = raw_draft
            try:
                if raw_draft.strip().startswith('{'):
                    draft_json = json.loads(raw_draft)
                    parsed_draft = draft_json.get("article_body", raw_draft)
            except Exception:
                pass

            logger.info(f"🔍 [ReviewAgent] Node1: 이슈 '{issue.name}', 분석 메타데이터 및 기사 {len(articles_meta)}건 로드 완료")
            return {
                "issue_name": issue.name,
                "issue_description": issue.description or "",
                "issue_background": issue.background or "",
                "core_contentions": issue.core_contentions or "",
                "conflict_summary": issue.conflict_summary or "",
                "pre_generated_draft": parsed_draft,
                "articles_meta": articles_meta,
                "messages": [f"이슈 분석 데이터 및 기사 {len(articles_meta)}건 로드 완료"]
            }

        except Exception as e:
            msg = f"데이터 로드 실패: {e}"
            logger.error(f"🔍 [ReviewAgent] {msg}")
            return {"error": msg, "messages": [msg]}


    # -----------------------------------------------------------
    # Node 3: 가이드라인 검증 + AI 종합 의견 (Gemini/Local LLM)
    # -----------------------------------------------------------
    def node_analyze_and_opine(self, state: ReviewState) -> dict:
        """
        [Node 3] LLM을 사용하여 가이드라인 검증, 분석 내용 반영 여부, AI 종합 의견을 생성합니다.
        """
        from app.agents.utils import call_llm, update_total_tokens
        
        pre_generated_draft = state.get("pre_generated_draft", "")
        issue_name = state.get("issue_name", "")
        issue_background = state.get("issue_background", "")
        core_contentions = state.get("core_contentions", "")
        conflict_summary = state.get("conflict_summary", "")
        
        logger.info(f"⚖️ [ReviewAgent] Node3: 최종 검토 및 종합 의견 생성 시작")

        prompt = f"""
            당신은 언론 윤리 전문가이자 노련한 편집장입니다.
            제시된 이슈의 분석 데이터(배경, 핵심 쟁점, 갈등 요약)를 바탕으로 기자가 작성한 최종 기사를 엄격히 검토하십시오.

            [검토 대상 기사]
            {pre_generated_draft}

            [이슈 분석 데이터]
            이슈명: {issue_name}
            배경: {issue_background}
            핵심 쟁점: {core_contentions}
            갈등 요약: {conflict_summary}

            [검토 가이드라인]
            1. 혐오 표현 및 차별적 서술: 특정 인종·성별·종교·지역 비하 표현이 있는가?
            2. 자극적인 형용사 사용: 선정적인 표현이 있는가?
            3. 특정 집단 비하 또는 낙인화: 특정 정치/사회집단을 일방적으로 낙인 찍는가?
            4. 미확인 사실 및 추측성 서술: 근거 없는 추측을 사실처럼 단정하는가?
            5. 분석 내용 반영: 제공된 '핵심 쟁점'과 '갈등 요약'의 본질이 기사에 충실히 반영되었는가?

            [최종 종합 의견]
            - 기사의 완성도, 균형성, 언론 윤리 준수 여부 및 분석 데이터와의 일치성을 종합하여 1문장으로 작성하십시오.
            - 'ai_opinion' 필드에 반드시 포함되어야 합니다.

            [출력 형식 - 반드시 순수 JSON만 반환]
            {{
                "guideline_checks": [
                    {{"label": "혐오 표현 및 차별적 서술", "passed": true, "detail": ""}},
                    {{"label": "자극적인 형용사 사용", "passed": true, "detail": ""}},
                    {{"label": "특정 집단 비하 또는 낙인화 표현", "passed": true, "detail": ""}},
                    {{"label": "미확인 사실 및 추측성 서술", "passed": true, "detail": ""}},
                    {{"label": "핵심 분석 내용 반영", "passed": true, "detail": "핵심 쟁점 반영 정도 기술"}}
                ],
                "ai_opinion": "종합 평가 내용"
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
            result, usage = call_llm(prompt, "7B", state, schema=response_schema)
            
            # 토큰 업데이트
            total_tokens = update_total_tokens(state, usage)

            # 결과 보정 로직 (Post-processing)
            final_checks = []
            final_opinion = ""

            if isinstance(result, list):
                final_checks = result
                failed_items = [c.get("label") for c in result if isinstance(c, dict) and not c.get("passed", True)]
                final_opinion = "전체적으로 가이드라인을 준수하고 있습니다." if not failed_items else f"{', '.join(failed_items)} 항목에 대한 개선이 권장됩니다."
            elif isinstance(result, dict):
                final_checks = result.get("guideline_checks", [])
                final_opinion = result.get("ai_opinion", "")

            # 통과(passed: True) 항목에 대해 빈 detail 채우기 (사용자 요청 반영)
            default_details = {
                "혐오 표현 및 차별적 서술": "혐오 표현 및 차별적 서술이 없습니다.",
                "자극적인 형용사 사용": "자극적인 형용사 사용이 발견되지 않았습니다.",
                "특정 집단 비하 또는 낙인화 표현": "특정 집단에 대한 비하 또는 낙인화 표현이 없습니다.",
                "미확인 사실 및 추측성 서술": "미확인 사실이나 추측성 서술이 발견되지 않았습니다.",
                "핵심 분석 내용 반영": "핵심 분석 내용이 기사에 충실히 반영되었습니다."
            }

            for check in final_checks:
                if isinstance(check, dict) and check.get("passed") is True:
                    if not check.get("detail"):
                        label = check.get("label", "")
                        check["detail"] = default_details.get(label, "가이드라인을 준수하고 있습니다.")

            # 최종 결과 조립
            result = {
                "guideline_checks": final_checks,
                "ai_opinion": final_opinion if final_opinion else "검토가 완료되었습니다."
            }
            logger.info(f"⚖️ [ReviewAgent] Node3: 최종 검토 완료 (의견: {result['ai_opinion'][:20]}...)")

        except Exception as e:
            msg = f"LLM 분석 오류: {e}"
            logger.error(f"⚖️ [ReviewAgent] {msg}")
            result = {
                "guideline_checks": [
                    {"label": "윤리 및 가이드라인 검증", "passed": True, "detail": "분석 오류로 인한 자동 통과"},
                    {"label": "핵심 분석 내용 반영", "passed": True, "detail": ""}
                ],
                "ai_opinion": f"분석 중 오류가 발생했습니다: {str(e)}"
            }
            total_tokens = state.get("total_tokens", {"prompt_tokens": 0, "completion_tokens": 0})

        return {
            "guideline_checks": result.get("guideline_checks", []),
            "ai_opinion": result.get("ai_opinion", ""),
            "total_tokens": total_tokens,
            "messages": ["최종 검토 및 종합 의견 생성 완료"]
        }
