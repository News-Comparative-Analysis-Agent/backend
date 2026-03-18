import json
import google.generativeai as genai
from app.agents.state import ComparisonState
from app.agents.utils import parse_llm_json, update_total_tokens
from app.core.logger import logger, log_llm_event
from langsmith import traceable

class JudgeAgent:
    """
    Agent 5) Judge Agent (품질 검증 + 재생성 판단)
    • 입력: 최종 JSON 문서 + 쟁점 + 주장카드
    • 출력(JSON): 점수/검증지표/행동지침 포함된 v2.0 평가 데이터
      o metrics: claims_utilization, media_diversity 등
      o action: "PROCEED", "RETRY_FROM_WRITER", "RETRY_FROM_EDITOR"
      o feedback: summary, rejection_reason (FAIL 시)
    """
    def __init__(self, db=None):
        self.db = db

    @traceable(name="Agent 5: Judge (최종 검수) ⚖️")
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
        
        # edited_article이 dict일 경우 len()이 key 개수를 반환하므로 문자열로 변환
        article_str = json.dumps(edited_article, ensure_ascii=False) if isinstance(edited_article, dict) else str(edited_article)
        logger.info(f"⚖️ [JudgeAgent] 입력 데이터: 기사길이={len(article_str)}, 쟁점수={len(structured_issues)}, 주장카드수={len(claim_cards)}")
        
        # 타입에 상관없이 오류 여부를 문자열로 판단
        if not edited_article or "오류가 발생" in article_str:
            msg = "초안이 없어 검증 불가"
            logger.warning(f"⚖️ [JudgeAgent] {msg}")
            return {"judge_status": "FAIL_WRITER", "judge_feedback": msg, "retry_count": retry_count + 1, "messages": [msg]}
            
        issues_json = json.dumps(structured_issues, ensure_ascii=False)
        
        prompt = f"""
        당신은 편집국장(Judge)입니다. 기자(Writer)와 데스크(Editor)를 거쳐 완성된 '최종 JSON 비평 기사'를 엄격히 검증하십시오.
        
        [검증 대상 최종 기사 (JSON)]
        {json.dumps(edited_article, ensure_ascii=False, indent=2) if isinstance(edited_article, dict) else edited_article}
        
        [원본 쟁점 데이터]
        {issues_json}
        
        [검증 항목]
        1. claims_utilization (주장 활용): 원본 쟁점 데이터에 있는 핵심 주장이 누락 없이 초안에 반영되었는가? (주요 주장 누락 시 RETRY_FROM_WRITER)
        2. media_diversity (매체 다양성): 제공된 쟁점 데이터 내의 다양한 출처 매체들이 편중되지 않고 골고루 기사에 인용되었는가? (원문에 매체가 적다면 있는 것만 잘 쓰여도 통과)
        3. factual_accuracy (사실 정확성): 지어낸 허위 사실 없이 원본 인용구가 맥락에 맞게 쓰였는가? (조작 정황 시 RETRY_FROM_WRITER)
        4. draft_professionalism (기사 전문성): 문장이 지나치게 반복되지 않고 논리적인 신문 기사 톤을 갖췄는가? (단순 톤/문맥 불량 시 RETRY_FROM_EDITOR)
        
        모든 기준을 통과하면 action을 "PROCEED", 내용의 근본적 수정/보강이 필요하면 "RETRY_FROM_WRITER", 단순 문장 교정이 필요하면 "RETRY_FROM_EDITOR"로 설정하십시오.
        total_score는 100점 만점으로 각 지표의 평균을 내어 정수형으로 기입하십시오 (70점 이상이면 PROCEED).

        [출력 규칙]
        1. status는 "PASS" 또는 "FAIL"로만 설정합니다. (action이 PROCEED면 PASS)
        2. 통과(PASS)인 경우, feedback의 summary에는 사족 없이 "통과"라고만 적거나 아주 짧은 1문장만 적으십시오. (절대 주석이나 변명을 덧붙이지 마십시오.)
        3. 실패(FAIL)인 경우에만 rejection_reason과 redo_instruction에 왜 실패했는지, 무엇을 고쳐야 하는지 상세히 적으십시오. 통과 시에는 "해당 없음"이라고 짧게 적으십시오.
        
        [반환 형식 예시]
        {{
            "status": "PASS",
            "total_score": 92,
            "metrics": {{
                "claims_utilization": 95,
                "media_diversity": 90,
                "factual_accuracy": 94,
                "draft_professionalism": 90
            }},
            "action": "PROCEED",
            "feedback": {{
                "summary": "종합 평가 한 줄",
                "rejection_reason": "해당 없음",
                "redo_instruction": "해당 없음"
            }}
        }}
        """
        
        try:
            # Judge는 환각 및 로직 검증의 핵심 장치이므로 가장 똑똑한 Gemini 사용 강제
            response_schema = {
                "type": "OBJECT",
                "properties": {
                    "status": {"type": "STRING"},
                    "total_score": {"type": "INTEGER"},
                    "metrics": {
                        "type": "OBJECT",
                        "properties": {
                            "claims_utilization": {"type": "INTEGER"},
                            "media_diversity": {"type": "INTEGER"},
                            "factual_accuracy": {"type": "INTEGER"},
                            "draft_professionalism": {"type": "INTEGER"}
                        },
                        "required": ["claims_utilization", "media_diversity", "factual_accuracy", "draft_professionalism"]
                    },
                    "action": {"type": "STRING"},
                    "feedback": {
                        "type": "OBJECT",
                        "properties": {
                            "summary": {"type": "STRING"},
                            "rejection_reason": {"type": "STRING"},
                            "redo_instruction": {"type": "STRING"}
                        },
                        "required": ["summary", "rejection_reason", "redo_instruction"]
                    }
                },
                "required": ["status", "total_score", "metrics", "action", "feedback"]
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
            total_tokens = update_total_tokens(state, usage, "JudgeAgent")

            if not result:
                logger.warning("Judge JSON 파싱 실패 -> 안전망 강제 PASS 처리")
                return {"judge_status": "PASS", "judge_feedback": "", "messages": ["파싱 실패로 강제 패스"], "total_tokens": total_tokens}
                
            # 명세서(v2.0)의 action을 기존 시스템의 라우팅 상태(judge_status)로 매핑
            action = result.get("action", "RETRY_FROM_WRITER").upper()
            if action in ["PROCEED", "PASS"]:
                status = "PASS"
            elif action == "RETRY_FROM_EDITOR":
                status = "FAIL_EDITOR"
            else:
                status = "FAIL_WRITER"
                
            feedback_dict = result.get("feedback", {})
            summary = feedback_dict.get("summary", "")
            reason = feedback_dict.get("rejection_reason", "")
            instruction = feedback_dict.get("redo_instruction", "")
            
            # 피드백 문자열 조합 (해당 없음인 경우 제외)
            feedback_parts = []
            if summary and "해당 없음" not in summary: feedback_parts.append(summary)
            if reason and "해당 없음" not in reason: feedback_parts.append(f"이유: {reason}")
            if instruction and "해당 없음" not in instruction: feedback_parts.append(f"지시: {instruction}")
            
            feedback = " | ".join(feedback_parts)
            if not feedback.strip():
                feedback = "피드백을 제공하지 않았습니다."
                
            score = result.get("total_score", 0)
            
            msg = f"검수 완료: {status} (점수: {score}, 피드백: {feedback})"
            
            # 🚨 최대 재시도 도달 시 강제 통과 처리 (Best Effort 저장)
            if retry_count >= 2 and status != "PASS":
                logger.warning(f"⚖️ [JudgeAgent] 최대 재시도(3회) 도달. 현재 상태({status})를 무시하고 강제 PASS 처리하여 초안을 저장합니다.")
                status = "PASS"
                msg += " -> [강제 PASS]"
                
            if status == "PASS":
                logger.success(f"⚖️ [JudgeAgent] {msg}")
                # 최종 통과 시 DB에 모든 분석 결과 저장 (웹 서비스 조회용)
                issue_id = state.get("issue_id")
                if issue_id and self.db:
                    from app.scroller.repository import ScrollerRepository
                    repo = ScrollerRepository(self.db)
                    
                    # 1. 초안 저장: 최종 완성된 Dict를 JSON String으로 변환하여 DB에 저장
                    edited_json_str = json.dumps(edited_article, ensure_ascii=False) if isinstance(edited_article, dict) else str(edited_article)
                    repo.update_issue_draft(issue_id, edited_json_str)
                    
                    # 2. 나머지 분석 메타데이터(background, description) 저장
                    repo.update_issue_analysis_results(
                        issue_id=issue_id,
                        description=state.get("description"),
                        background=state.get("background"),
                    )
                    self.db.commit() # 지연된 저장소 작업 영구 반영
                    logger.info(f"⚖️ [JudgeAgent] 모든 분석 결과(초안, 배경, 요약)가 DB(IssueLabel)에 저장되었습니다. (Issue ID: {issue_id})")
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
