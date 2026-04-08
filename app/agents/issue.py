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
        media_json = json.dumps(media_items, ensure_ascii=False, indent=2)
        prompt = f"""
            당신은 기득권 언론의 위선적인 프레임을 파헤치는 **미디어 비평지 편집국장**입니다. 
            아래 [매체별 분석 데이터]에는 각 언론사가 사건을 어떻게 '가공'했는지에 대한 분석(`narrative`)이 담겨 있습니다.

            [매체별 분석 데이터]
            {media_json}

            요청:
            1) 모든 응답은 **한국어로만 작성**하십시오.
            2) `conflict_summary`: 단순히 입장을 나열하지 마십시오. **어느 매체가 본질을 은폐하고 있으며, 어떤 매체가 실체적 진실을 추적하고 있는지 그 '전선(Battle line)'을 명확히 규정하십시오.** - 특히 보수/진보 매체가 같은 팩트를 두고 사용하는 '단어의 비대칭성'을 비판적으로 요약하십시오.
            
            [비평적 지침]
            - "~라고 엇갈립니다" 대신 **"~라는 프레임으로 본질을 흐리고 있습니다"**와 같은 확정적 표현을 사용하십시오.
            - 매체들이 공통적으로 침묵하고 있는 지점이 있다면 이를 날카롭게 지적하십시오.

            [응답 예시 - 이 정도의 날카로움을 유지하십시오]
            {{
                "conflict_summary": "검찰의 수사 거래 의혹이라는 본질을 두고, 보수 언론은 '녹취록 공개의 불순한 의도'를 부각하며 메신저 공격에 화력을 집중하는 반면, 진보 언론은 '사법 정의의 타락'을 경고하며 정면 돌파를 선택했습니다. 언론이 감시자가 아닌 진영의 호위무사로 전락한 공론장의 비극이 이 갈등의 핵심입니다."
            }}

            아래 JSON만 출력하십시오.
            {{
                "conflict_summary": "매체 간 프레임 전쟁의 본질과 기만성을 폭로하는 요약문"
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
