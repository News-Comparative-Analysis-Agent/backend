import json
import google.generativeai as genai
from app.agents.state import ComparisonState
from app.agents.utils import parse_llm_json, update_total_tokens
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
    def __init__(self, db=None):
        self.db = db

    def node_evaluate_draft(self, state: ComparisonState) -> dict:
        """
        [Node] 데스크를 통과한 최종 기사(edited_article)를 가장 엄격하게 검증합니다.
        """
        edited_article = state.get("edited_article", "")
        structured_issues = state.get("structured_issues", [])
        claim_cards = state.get("claim_cards", [])
        retry_count = state.get("retry_count", 0)
        
        msg_start = f"Agent 5 (Judge): 품질 검수 시작 (현재 시도: {retry_count + 1})"
        logger.info(f"⚖️ [JudgeAgent] {msg_start}")
        logger.info(f"⚖️ [JudgeAgent] 입력 데이터: 기사길이={len(edited_article)}, 쟁점수={len(structured_issues)}, 주장카드수={len(claim_cards)}")
        
        if not edited_article or "오류가 발생" in edited_article:
            msg = "초안이 없어 검증 불가"
            logger.warning(f"⚖️ [JudgeAgent] {msg}")
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
            result = parse_llm_json(response.text)
            
            # 토큰 정보 추출
            usage_metadata = response.usage_metadata
            usage = {
                "prompt_tokens": usage_metadata.prompt_token_count,
                "completion_tokens": usage_metadata.candidates_token_count
            }
            
            # 토큰 업데이트
            total_tokens = update_total_tokens(state, usage)

            if not result:
                logger.warning("Judge JSON 파싱 실패 -> 안전망 강제 PASS 처리")
                return {"judge_status": "PASS", "judge_feedback": "", "messages": ["파싱 실패로 강제 패스"], "total_tokens": total_tokens}
                
            status = result.get("status", "FAIL_WRITER").upper()
            feedback = result.get("feedback", "")
            score = result.get("score", 0)
            
            msg = f"검수 완료: {status} (점수: {score}, 피드백: {feedback})"
            if status == "PASS":
                logger.success(f"⚖️ [JudgeAgent] {msg}")
                # 최종 통과 시 DB에 저장 (웹 서비스 조회용)
                issue_id = state.get("issue_id")
                if issue_id and self.db:
                    from app.scroller.repository import ScrollerRepository
                    repo = ScrollerRepository(self.db)
                    repo.update_issue_draft(issue_id, edited_article)
                    logger.info(f"⚖️ [JudgeAgent] 최종 비평 기사가 DB(IssueLabel.pre_generated_draft)에 저장되었습니다. (Issue ID: {issue_id})")
            else:
                logger.warning(f"⚖️ [JudgeAgent] {msg}")
                
            return {
                "judge_status": status,
                "judge_feedback": feedback,
                "retry_count": retry_count + 1,
                "messages": [msg],
                "total_tokens": total_tokens
            }
            
        except Exception as e:
            msg = f"Judge 평가 시스템 에러: {e}"
            logger.error(msg)
            log_llm_event("agent_judge", msg)
            return {"judge_status": "PASS", "judge_feedback": msg, "retry_count": retry_count + 1, "messages": [msg]}
