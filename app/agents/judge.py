import json
import os
import google.generativeai as genai
from app.agents.state import ComparisonState
from app.agents.utils import parse_llm_json, update_total_tokens
from app.core.logger import logger, log_llm_event
from langsmith import traceable

class JudgeAgent:
    """
    Agent 5) Judge Agent (품질 검증 + 재생성 판단)
    • 입력: 최종 JSON 문서 + 원본 데이터(media_views, 이슈 메타데이터)
    • 출력(JSON): 점수/검증지표/행동지침 포함된 평가 데이터
    """
    def __init__(self, db=None):
        self.db = db

    @traceable(name="Agent 5: Judge (최종 검수) ⚖️")
    def node_evaluate_draft(self, state: ComparisonState) -> dict:
        """
        [Node] 데스크를 통과한 최종 기사(edited_article)를 원본 데이터(media_views 등)와 대조 검증합니다.
        """
        edited_article = state.get("edited_article", "")
        media_views = state.get("media_views", []) or []
        
        # 이슈 메타데이터 (맥락 파악용)
        issue_context = {
            "title": state.get("title", ""),
            "description": state.get("description", ""),
            "background": state.get("background", ""),
            "core_contentions": state.get("core_contentions", ""),
            "conflict_summary": state.get("conflict_summary", "")
        }
        
        retry_count = state.get("retry_count", 0)
        
        msg_start = f"Agent 5 (Judge): 품질 검수 시작 (현재 시도: {retry_count + 1})"
        logger.info(f"⚖️ [JudgeAgent] {msg_start}")

        # 상세 입력 데이터 로깅 (사용자 요청: 인풋으로 받은값도 로그로 기록)
        log_llm_event("agent_judge", "품질 검토 입력 데이터 상세", details={
            "issue_context": issue_context,
            "media_views": media_views,
            "edited_article": edited_article
        })
        
        # 입력 데이터 요약 로깅
        article_str = json.dumps(edited_article, ensure_ascii=False) if isinstance(edited_article, dict) else str(edited_article)
        logger.info(f"⚖️ [JudgeAgent] 입력 데이터: 최종기사길이={len(article_str)}, 근거수={len(media_views)}")
        
        if not edited_article or "오류가 발생" in article_str:
            msg = "최종 결과물이 없어 검증 불가"
            logger.warning(f"⚖️ [JudgeAgent] {msg}")
            return {"judge_status": "FAIL_WRITER", "judge_feedback": msg, "retry_count": retry_count + 1, "messages": [msg]}
            
        source_data_json = json.dumps({
            "issue_context": issue_context,
            "media_views": media_views
        }, ensure_ascii=False, indent=2)
        
        prompt = f"""
        당신은 편집국장(Judge)입니다. 최종 완성된 비평 기사가 원본 데이터(Evidence/Issue 분석 결과)의 내용을 정확하고 충실히 반영했는지 검증하십시오.
        
        [검증 대상: 최종 기사]
        {json.dumps(edited_article, ensure_ascii=False, indent=2) if isinstance(edited_article, dict) else edited_article}
        
        [원본 데이터 (Source Truth)]
        {source_data_json}
        
        [검증 항목]
        1. factual_consistency: 원본 데이터에 명시된 사실관계(언론사별 주장, 인용구 등)가 왜곡되거나 자의적으로 해석되지 않았는가?
        2. claims_coverage: 원본 데이터의 핵심 쟁점과 근거 자료들이 누락 없이 기사에 충분히 반영되었는가?
        3. logical_cohesion: 기사가 전체적인 맥락(issue_context)에 맞게 논리적 완결성을 갖추고 있는가?
        4. professional_tone: 신뢰할 수 있는 비평 기사로서의 전문적이고 객관적인 어조를 유지하고 있는가?
        
        [의사 결정 지침]
        - 모든 기준 통과 시 action: "PROCEED"
        - 팩트 오류나 핵심 근거 누락 등 중대한 결함 시 action: "RETRY_FROM_WRITER"
        - 문장력, 톤, 맥락 개선이 필요한 경우 action: "RETRY_FROM_EDITOR"
        
        total_score는 100점 만점으로 평가하십시오 (70점 이상이면 PROCEED).
        """
        
        try:
            genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
            
            response_schema = {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "total_score": {"type": "integer"},
                    "metrics": {
                        "type": "object",
                        "properties": {
                            "factual_consistency": {"type": "integer"},
                            "claims_coverage": {"type": "integer"},
                            "logical_cohesion": {"type": "integer"},
                            "professional_tone": {"type": "integer"}
                        },
                        "required": ["factual_consistency", "claims_coverage", "logical_cohesion", "professional_tone"]
                    },
                    "action": {"type": "string"},
                    "feedback": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string"},
                            "rejection_reason": {"type": "string"},
                            "redo_instruction": {"type": "string"}
                        },
                        "required": ["summary", "rejection_reason", "redo_instruction"]
                    }
                },
                "required": ["status", "total_score", "metrics", "action", "feedback"]
            }
            
            gen_model = genai.GenerativeModel(
                'gemini-2.0-flash', 
                generation_config={"response_mime_type": "application/json", "response_schema": response_schema}
            )
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
                
            # action을 judge_status로 매핑
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
            
            # 피드백 문자열 조합
            feedback_parts = []
            if summary and "해당 없음" not in summary: feedback_parts.append(summary)
            if reason and "해당 없음" not in reason: feedback_parts.append(f"이유: {reason}")
            if instruction and "해당 없음" not in instruction: feedback_parts.append(f"지시: {instruction}")
            
            feedback = " | ".join(feedback_parts)
            if not feedback.strip():
                feedback = "피드백을 제공하지 않았습니다."
                
            score = result.get("total_score", 0)
            
            msg = f"검수 완료: {status} (점수: {score})"
            log_llm_event("agent_judge", msg, details=result)
            
            # 🚨 최대 재시도 도달 시 강제 통과 처리
            if retry_count >= 2 and status != "PASS":
                logger.warning(f"⚖️ [JudgeAgent] 최대 재시도(3회) 도달. 현재 상태({status})를 무시하고 강제 PASS 처리하여 초안을 저장합니다.")
                status = "PASS"
                msg += " -> [강제 PASS]"
                
            if status == "PASS":
                logger.success(f"⚖️ [JudgeAgent] {msg}")
                # 최종 통과 시 DB에 모든 분석 결과 저장
                issue_id = state.get("issue_id")
                if issue_id and self.db:
                    from app.scroller.repository import ScrollerRepository
                    repo = ScrollerRepository(self.db)
                    
                    # 초안 저장
                    edited_json_str = json.dumps(edited_article, ensure_ascii=False) if isinstance(edited_article, dict) else str(edited_article)
                    repo.update_issue_draft(issue_id, edited_json_str)
                    
                    # 나머지 분석 메타데이터 저장
                    repo.update_issue_analysis_results(
                        issue_id=issue_id,
                        description=state.get("description"),
                        background=state.get("background"),
                        core_contentions=state.get("core_contentions"),
                        conflict_summary=state.get("conflict_summary")
                    )
                    self.db.commit()
                    logger.info(f"⚖️ [JudgeAgent] 모든 분석 결과가 DB에 저장되었습니다. (Issue ID: {issue_id})")
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
            return {
                "judge_status": "FAIL_WRITER", 
                "judge_feedback": f"시스템 오류 발생으로 인한 자동 반려: {e}", 
                "retry_count": retry_count + 1, 
                "messages": [msg]
            }
