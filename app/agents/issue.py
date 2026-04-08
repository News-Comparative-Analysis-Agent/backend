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
            당신은 복잡한 사안의 이면을 꿰뚫어 보는 전문 논설위원입니다. 
            아래 [매체별 분석 데이터]를 읽고, 이번 사안을 바라보는 언론사들 간의 핵심 갈등 지점과 시각 차이를 **'대립 구도'** 관점에서 요약하세요.

            [매체별 분석 데이터]
            {media_json}

            요청:
            1) 모든 응답은 **반드시 한국어로만 작성**해야 합니다.
            2) `conflict_summary`를 하나의 문자열로 생성: 모든 언론사가 공통적으로 주목하는 핵심 이슈와 그 안에서 나타나는 시각 차이(프레임의 충돌)를 독자들이 이해하기 쉽게 분석하여 서술하세요.
               **단순한 사실 요약이 아니라, 매체들이 어떤 정치적/사회적 관점 차이를 보이는지에 집중하십시오.**

            [응답 예시]
            {{
                "conflict_summary": "정부의 의대 증원 정책에 대해 보수 언론은 '필수 의료 확충을 위한 불가피한 선택'이자 '법과 원칙의 준수'를 강조하는 반면, 진보 언론은 '정부의 일방적 불통 행정'이 사태를 키웠다고 분석하며 대화를 통한 사회적 합의를 촉구하고 있어 팽팽한 시각 차를 보입니다."
            }}

            아래 JSON만 출력하세요.
            {{
                "conflict_summary": "갈등의 본질과 매체 간 대립 구조를 분석한 요약문"
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
