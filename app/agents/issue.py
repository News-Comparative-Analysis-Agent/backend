import json
from app.agents.state import ComparisonState
from app.agents.utils import call_llm, update_total_tokens
from app.core.logger import logger, log_llm_event

class IssueAgent:
    """
    Agent 2) Issue Agent (쟁점 구조화)
    주장 카드들을 분석하여 서로 충돌하거나 보완하는 '핵심 쟁점(Points of Contention)' 구조를 생성합니다.
    """
    def __init__(self, db=None):
        pass

    def node_structure_issues(self, state: ComparisonState) -> dict:
        """
        [Node] 추출된 주장 카드들을 바탕으로 논쟁적인 쟁점 리스트를 생성합니다.
        """
        claim_cards = state.get("claim_cards", [])
        llm_mode = state.get("llm_mode", "local_priority")
        
        log_llm_event("agent_issue", f"Agent 2 (Issue): {len(claim_cards)}개 주장 기반 쟁점 구조화 시작")
        
        if not claim_cards:
            return {"structured_issues": [], "messages": ["주장 카드가 없어 Issue 중단"]}
            
        cards_json = json.dumps(claim_cards, ensure_ascii=False, indent=2)
        
        prompt = f"""
        당신은 상충하는 언론 보도를 분석하여 핵심 쟁점을 도출하는 분석 전문가입니다.
        아래 제공된 '주장 카드' 리스트를 읽고, 언론사들이 서로 다른 목소리를 내고 있는 핵심 쟁점(Issue)들을 구조화하세요.
        
        [주장 카드 목록]
        {cards_json}
        
        [쟁점 구조화 규칙]
        1. 쟁점명: 언론사 간 시각 차이가 뚜렷한 주제를 제목으로 설정.
        2. 양측 관점: 어떤 매체가 어떤 지점에서 대립하는지 서술.
        3. 출처 연결: 해당 쟁점과 관련된 매체명과 URL을 정확히 기재.
        
        반드시 다음 JSON 형식으로만 응답하세요.
        
        [JSON 출력 형식]
        [
          {{
            "issue_title": "쟁점 제목",
            "media_stances": "매체별 관점 비교 설명 (A사는 ~, 반면 B사는 ~)",
            "sources": [
              {{"press": "매체명", "url": "기사URL"}}
            ]
          }}
        ]
        """
        
        try:
            if llm_mode == "gemini_only":
                response_schema = {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "issue_title": {"type": "STRING"},
                            "media_stances": {"type": "STRING"},
                            "sources": {
                                "type": "ARRAY",
                                "items": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "press": {"type": "STRING"},
                                        "url": {"type": "STRING"}
                                    },
                                    "required": ["press", "url"]
                                }
                            }
                        },
                        "required": ["issue_title", "media_stances", "sources"]
                    }
                }
                from app.agents.utils import call_gemini
                structured_data, usage = call_gemini(prompt)
            else:
                structured_data, usage = call_llm(prompt, "7B_1", state)
            
            # 토큰 업데이트
            total_tokens = update_total_tokens(state, usage)
            
            if not structured_data:
                structured_data = []
                
            msg = f"총 {len(structured_data)}개의 핵심 쟁점 도출 완료"
            logger.success(f"🧩 [IssueAgent] {msg}")
            log_llm_event("agent_issue", msg)
            return {"structured_issues": structured_data, "messages": [msg], "total_tokens": total_tokens}
            
        except Exception as e:
            msg = f"쟁점 구조화 시스템 에러: {e}"
            logger.error(msg)
            log_llm_event("agent_issue", msg)
            return {"structured_issues": [], "messages": [msg]}
