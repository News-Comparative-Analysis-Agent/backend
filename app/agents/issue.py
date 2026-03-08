import json
import google.generativeai as genai
from app.agents.state import ComparisonState
from app.agents.utils import call_local_llm, parse_llm_json
from app.core.logger import logger, log_llm_event

class IssueAgent:
    """
    Agent 2) Issue Agent (쟁점 구조화)
    • 입력: 주장 카드 목록
    • 출력(JSON): 쟁점 3~6개로 구조화
      o 쟁점 제목
      o 매체별 차이(강조/비판/중립 등)
      o 해당 쟁점의 근거 claim_id (여기서는 article URL이나 press 명으로 맵핑)
    """
    def __init__(self):
        pass

    def node_structure_issues(self, state: ComparisonState) -> dict:
        """
        [Node] 주장 카드 목록을 읽고 쟁점(Issue Point) 단위로 묶어서 JSON 구조로 반환합니다.
        """
        claim_cards = state.get("claim_cards", [])
        llm_mode = state.get("llm_mode", "gemini_only")
        
        log_llm_event("agent_issue", f"Agent 2 (Issue): {len(claim_cards)}개의 주장 카드를 기반으로 쟁점 구조화 시작")
        
        if not claim_cards:
            return {"structured_issues": [], "messages": ["주장 카드가 부족하여 쟁점 구조화 불가"]}
            
        cards_json = json.dumps(claim_cards, ensure_ascii=False, indent=2)
        
        prompt = f"""
        당신은 뛰어난 데이터 아키텍트이자 뉴스 분석가입니다.
        아래 제공된 '주장 카드 목록'을 읽고, 
        이 이슈를 관통하는 핵심 쟁점(Point of Contention) 3~6개를 도출하여 구조화하십시오.
        각 쟁점별로 어느 매체가 어떤 차이(강조/비판/중립 등)를 보이는지 명시하고, 
        그 근거가 되는 언론사와 원문 URL을 꼭 연결하십시오.
        
        [주장 카드 목록]
        {cards_json}
        
        [반환 형식 - 순수 JSON List만]
        [
            {{
                "issue_title": "첫 번째 핵심 쟁점 제목",
                "media_differences": "매체별 시각 차이 (예: A 매체는 논란 강조, B 매체는 해명에 집중)",
                "evidence_sources": [
                    {{
                        "press": "A 매체",
                        "url": "해당 기사 URL"
                    }}
                ]
            }},
            ...
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
                            "media_differences": {"type": "STRING"},
                            "evidence_sources": {
                                "type": "ARRAY",
                                "items": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "press": {"type": "STRING"},
                                        "url": {"type": "STRING"}
                                    }
                                }
                            }
                        },
                        "required": ["issue_title", "media_differences", "evidence_sources"]
                    }
                }
                gen_model = genai.GenerativeModel('gemini-2.0-flash', generation_config={"response_mime_type": "application/json", "response_schema": response_schema})
                response = gen_model.generate_content(prompt)
                final_text = response.text
            else:
                final_text = call_local_llm("7B_1", prompt, json_mode=True)
                
            structured_data = parse_llm_json(final_text)
            
            # 파싱 결과가 딕셔너리면 리스트로 변환 시도
            if isinstance(structured_data, dict) and len(structured_data) == 1:
                key = list(structured_data.keys())[0]
                if isinstance(structured_data[key], list):
                    structured_data = structured_data[key]
                else:
                    structured_data = [structured_data]
            elif not isinstance(structured_data, list):
                structured_data = [{"issue_title": "구조화 파싱 실패", "media_differences": str(structured_data), "evidence_sources": []}]

            msg = f"총 {len(structured_data)}개의 핵심 쟁점 도출 완료"
            logger.success(f"🧩 [IssueAgent] {msg}")
            log_llm_event("agent_issue", msg)
            return {"structured_issues": structured_data, "messages": [msg]}
            
        except Exception as e:
            msg = f"쟁점 구조화 시스템 에러: {e}"
            logger.error(msg)
            log_llm_event("agent_issue", msg)
            return {"structured_issues": [], "messages": [msg]}
