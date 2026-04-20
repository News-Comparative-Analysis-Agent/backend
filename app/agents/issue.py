import json
from app.agents.state import ComparisonState
from app.agents.utils import call_llm, update_total_tokens
from app.core.logger import logger, log_llm_event
from langsmith import traceable
from app.domains.issues.repository import IssueRepository

class IssueAgent:
    """
    Agent 2) Issue Agent (쟁점 구조화)
    주장 카드들을 분석하여 서로 충돌하거나 보완하는 '핵심 쟁점(Points of Contention)' 구조를 생성합니다.
    """
    def __init__(self, db=None):
        self.db = db
        self.issue_repo = IssueRepository(db) if db is not None else None

    @traceable(name="Agent 2: Issue (갈등 양상 분석) 🧩")
    def node_structure_issues(self, state: ComparisonState) -> dict:
        """
        [Node] 추출된 매체별 주장들을 종합하여 전체적인 대립 구도(conflict_summary)를 생성합니다.
        """
        # 1. 전달받은 분석 데이터 확인
        media_items = state.get("media_views", []) or []
        msg_start = f"Agent 2 (Issue): {len(media_items)}개 매체 데이터 기반 통합 갈등 분석 시작"
        log_llm_event("agent_issue", msg_start)

        if not media_items:
            return {"messages": ["분석할 매체 뷰가 없습니다."], "media_views": [], "conflict_summary": ""}

        # 2. 대립 구도 분석을 위한 LLM 호출
        # 언론사별 블록으로 포매팅 (media_json 덩어리 대신 명시적 레이블 사용)
        media_blocks = ""
        for i, mv in enumerate(media_items, 1):
            media_blocks += f"""
--- [{i}번 언론사: {mv.get('press', '알수없음')}] ---
핵심주장(claim): {mv.get('claim', '')}
원문 근거(evidence): {mv.get('evidence', '')}
보도 프레임(narrative): {mv.get('narrative', '')}
"""

        prompt = f"""
            당신은 여러 언론사의 보도를 비교·분석하여 대립 구도를 정리하는 미디어 비평 기사 작성자입니다.
            아래 [언론사별 분석 데이터]를 바탕으로, 이 사안을 두고 언론사 간에 어떤 시각 차이가 있는지 요약하십시오.

            [언론사별 분석 데이터]
            {media_blocks}

            [작성 규칙]
            1. 모든 응답은 한국어로만 작성하십시오.
            2. 기자 자신의 의견이나 판단을 쓰지 마십시오. 각 언론사가 한 말을 바탕으로 서술하십시오.
            3. 각 언론사의 `핵심주장(claim)`과 `보도 프레임(narrative)` 문장을 최대한 그대로 활용하십시오.
            4. 대립하는 시각은 "반면"으로 구분하십시오.

            [conflict_summary 작성 지침]
            - 어떤 언론사가 어떤 입장을 취했는지 사실 중심으로 서술한다.
            - 이 문장은 기사의 리드(두 번째 문장)와 결론에 그대로 사용된다.
            - 아래 형식을 따른다:
              "주요 일간지의 반응은 '[A 언론사 군의 입장 요약]'과 '[B 언론사 군의 입장 요약]'으로 엇갈렸다.
               [A언론사]는 [A 입장을 원문 그대로]. 반면 [B언론사]는 [B 입장을 원문 그대로]."

            [출력 JSON 예시]
            {{
                "conflict_summary": "주요 일간지의 반응은 '전체 녹취록을 우선 공개해야 한다'와 '국정조사에서 진상을 규명해야 한다'로 엇갈렸다. 조선일보는 '이런 의문을 없앨 방법은 간단하다. 녹취록 전문을 공개하면 된다'고 했다. 반면 경향신문은 '검사가 야당 대표를 옭아매기 위해 형량거래를 시도하고 거짓 진술을 압박했다면 두말할 것도 없이 검찰권을 남용한 중대 범죄'라고 했다."
            }}
        """

        try:
            schema = {
                "type": "OBJECT",
                "properties": {
                    "conflict_summary": {"type": "STRING"}
                },
                "required": ["conflict_summary"]
            }

            result, usage = call_llm(prompt, "local", state, schema=schema)
            total_tokens = update_total_tokens(state, usage, "IssueAgent")

            conflict_summary = result.get("conflict_summary", "") if isinstance(result, dict) else ""

            msg = "통합 갈등 분석(conflict_summary) 생성 완료"
            log_llm_event("agent_issue", msg, details=conflict_summary)

            return {
                "conflict_summary": conflict_summary,
                "media_views": media_items, # 분석에 사용된 데이터를 그대로 Writer에게 전달
                "issue_payload_items": [], # 역할 소진 시 비움
                "messages": [msg],
                "total_tokens": total_tokens,
            }

        except Exception as e:
            logger.error(f"IssueAgent 분석 실패: {e}")
            return {"messages": [f"분석 오류: {e}"], "conflict_summary": "", "media_views": media_items}
