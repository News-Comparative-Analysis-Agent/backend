import json
import google.generativeai as genai
from app.agents.state import ComparisonState
from app.agents.utils import parse_llm_json
from app.core.logger import logger, log_llm_event

class JudgeAgent:
    """
    Agent 5) Judge Agent (품질 검증 + 재생성 판단)
    • 입력: 수정 초안 + 쟁점 + 주장카드
    • 출력(JSON): 점수/경고/재실행 지시
      o 출처 매체 수(최소 3)
      o 근거 존재 여부
      o 중복률
      o status: "PASS", "FAIL_WRITER" (내용 부족), "FAIL_EDITOR" (톤/문맥 불량)
    """
    def __init__(self):
        pass

    def node_evaluate_draft(self, state: ComparisonState) -> dict:
        """
        [Node] 데스크를 통과한 최종 기사(edited_article)를 가장 엄격하게 검증합니다.
        """
        edited_article = state.get("edited_article", "")
        structured_issues = state.get("structured_issues", [])
        claim_cards = state.get("claim_cards", [])
        retry_count = state.get("retry_count", 0)
        
        log_llm_event("agent_judge", f"Agent 5 (Judge): 품질 검수 시작 (현재 시도: {retry_count + 1})")
        
        if not edited_article or "오류가 발생" in edited_article:
            msg = "초안이 없어 검증 불가"
            return {"judge_status": "FAIL_WRITER", "judge_feedback": msg, "retry_count": retry_count + 1, "messages": [msg]}
            
        issues_json = json.dumps(structured_issues, ensure_ascii=False)
        
        prompt = f"""
        당신은 편집국장(Judge)입니다. 기자(Writer)와 데스크(Editor)를 거쳐 올라온 최종 비평 기사를 검증하십시오.
        
        [검증 대상 최종 기사]
        {edited_article}
        
        [원본 쟁점 데이터]
        {issues_json}
        
        [검증 항목]
        1. 매체 다양성: 기사에 언급된 출처(매체)가 최소 3개 이상인가? (부족하면 FAIL_WRITER)
        2. 근거 존재 여부: 각 쟁점 끝에 "근거([매체명](URL))" 형태로 출처가 명확히 달려 있는가? (없거나 지어냈다면 FAIL_WRITER)
        3. 문맥/논리성(중복률): 문장이 지나치게 반복되거나 톤앤매너가 신문 기사에 맞지 않는가? (에디팅이 불량하면 FAIL_EDITOR)
        
        모든 기준을 완벽히 통과하면 status를 "PASS"로 하십시오.
        
        [반환 형식 - 순수 JSON만]
        {{
            "status": "PASS", // 또는 "FAIL_WRITER", "FAIL_EDITOR"
            "score": 85, // 0~100점 품질 점수
            "warnings": ["경고 사항 1", "경고 사항 2..."], // 없으면 빈 배열
            "feedback": "재작성/재수정 시 반영할 구체적 지침 (PASS 시 비워둠)"
        }}
        """
        
        try:
            # Judge는 환각 및 로직 검증의 핵심 장치이므로 가장 똑똑한 Gemini 사용 강제
            response_schema = {
                "type": "OBJECT",
                "properties": {
                    "status": {"type": "STRING"},
                    "score": {"type": "INTEGER"},
                    "warnings": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "feedback": {"type": "STRING"}
                },
                "required": ["status", "score", "warnings", "feedback"]
            }
            gen_model = genai.GenerativeModel('gemini-2.0-flash', generation_config={"response_mime_type": "application/json", "response_schema": response_schema})
            response = gen_model.generate_content(prompt)
            
            # Gemini 2.0 JSON Schema 모드에서는 response.text가 순수 JSON임을 보장합니다.
            try:
                result = json.loads(response.text)
            except json.JSONDecodeError as je:
                logger.error(f"Judge JSON 파싱 치명적 실패: {je}\nRaw: {response.text}")
                return {
                    "judge_status": "FAIL_WRITER", 
                    "judge_feedback": "Judge 결과 데이터 파싱 실패 (시스템 오류). 재검증을 위해 다시 작성하십시오.", 
                    "retry_count": retry_count + 1,
                    "messages": ["JSON 파싱 에러로 인한 강제 반려"]
                }
            
            if not result:
                logger.warning("Judge 결과값이 비어있음 -> 안전을 위해 반려 처리")
                return {
                    "judge_status": "FAIL_WRITER", 
                    "judge_feedback": "Judge 평가 결과가 생성되지 않았습니다. 다시 시도하십시오.", 
                    "retry_count": retry_count + 1,
                    "messages": ["빈 결과값으로 인한 반려"]
                }
                
            status = result.get("status", "FAIL_WRITER").upper()
            feedback = result.get("feedback", "피드백이 제공되지 않았습니다.")
            score = result.get("score", 0)
            
            msg = f"검수 완료: {status} (점수: {score}, 피드백: {feedback})"
            log_llm_event("agent_judge", msg)
            
            return {
                "judge_status": status,
                "judge_feedback": feedback,
                "retry_count": retry_count + 1,
                "messages": [msg]
            }
            
        except Exception as e:
            msg = f"Judge 평가 시스템 치명적 에러: {e}"
            logger.error(msg)
            log_llm_event("agent_judge", msg)
            # 🔥 시스템 에러 발생 시 절대 PASS 시키지 않고 FAIL_WRITER로 돌려보내 안전장치 가동
            return {
                "judge_status": "FAIL_WRITER", 
                "judge_feedback": f"시스템 오류 발생으로 인한 자동 반려: {e}", 
                "retry_count": retry_count + 1, 
                "messages": [msg]
            }
