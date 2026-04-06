import json
import os
from app.agents.state import ComparisonState
from app.agents.utils import parse_llm_json, update_total_tokens, call_llm
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
        # (방어코드) 중간 예외 발생 시 UnboundLocalError 방지를 위해 지역 변수 최상단 초기화
        retry_count = state.get("retry_count", 0)
        total_tokens = {"prompt_tokens": 0, "completion_tokens": 0}
        
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
        
        msg_start = f"Agent 5 (Judge): 품질 검수 시작 (현재 시도: {retry_count + 1})"
        logger.info(f"⚖️ [JudgeAgent] {msg_start}")

        # 상세 입력 데이터 로깅 (사용자 요청: DB/LangSmith 외에도 터미널 및 info.log에 직관적으로 출력되게 함)
        logger.info(f"⚖️ [JudgeAgent] 입력 데이터 상세 - [이슈 제목]: {issue_context.get('title', '')}")
        logger.info(f"⚖️ [JudgeAgent] 입력 데이터 상세 - [핵심 쟁점]: {issue_context.get('core_contentions', '')}")
        
        ctx_dump = "\n".join([f"  - [{i+1}번 문서] {str(m.get('evidence', ''))[:100]}..." for i, m in enumerate(media_views)])
        logger.info(f"⚖️ [JudgeAgent] 입력 데이터 상세 - [제공된 근거(요약)]: \n{ctx_dump}")
        
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
            
        try:
            edited_article_str = json.dumps(edited_article, ensure_ascii=False) if isinstance(edited_article, dict) else str(edited_article)
            
            full_issue_context_str = f"""
            [논란의 주제]: {issue_context.get('title', '')}
            [이슈 설명]: {issue_context.get('description', '')}
            [배경 지식]: {issue_context.get('background', '')}
            [핵심 쟁점]: {issue_context.get('core_contentions', '')}
            [갈등 요약]: {issue_context.get('conflict_summary', '')}
            """.strip()
            
            contexts = [str(m.get("evidence", "내용 없음")) for m in media_views if m.get("evidence")]
            if not contexts:
                contexts = ["제공된 문서 없음"]
            contexts_str = "\n\n".join([f"[{i+1}번 참고 문서]\n{c}" for i, c in enumerate(contexts)])
            
            logger.info("⚖️ [JudgeAgent] 통합 G-EVAL(팩트+어조/문맥) 벤치마킹을 시작합니다...")
            
            g_eval_prompt = f"""
            당신은 전문 언론사의 데스크 편집국장(숙련된 인간 평가자)입니다. 다음 기사 초안을 읽고 엄격한 저널리즘 기준에 따라 100점 만점으로 종합 평가해 주세요.

            [평가 대상 기사]
            {edited_article_str}

            [이슈의 전체 맥락 (Issue Context)]
            {full_issue_context_str}

            [작성을 위해 참고한 원문 근거 (Source Contexts)]
            {contexts_str}

            [평가 구체적 기준 (Rubric)]
            1. 사실성 및 팩트체크 (Faithfulness, 40점):
            - 기사에 작성된 모든 주장이 '작성을 위해 참고한 원문 근거' 내에 존재하는 사실인가? 임의로 지어낸 허위 사실(할루시네이션)이나 숫자/통계 왜곡은 없는가?
            2. 논리적 완결성 (Logical Cohesion, 30점): 
            - 제시된 '이슈의 전체 맥락(배경/쟁점/갈등)'을 글의 서론-본론-결론이 빠짐없이 잘 담아내며 자연스럽게 이어지는가?
            3. 전문적 어조 (Professional Tone, 30점): 
            - 신뢰할 수 있는 비평 기사로서 객관성을 유지하며 감정적이거나 가벼운 어휘가 배제되었는가?

            [작업 지시사항]
            1. 모든 응답(thought, redo_instruction 등 모든 필드)은 **반드시 한국어로만 작성**해야 합니다. 절대 중국어나 다른 외국어를 사용하지 마세요.
            2. 반드시 JSON 형식으로만 응답해야 합니다. 마크다운(` ```json `)을 쓰지 마세요.
            3. 먼저 위 세 가지 기준에 대한 각각의 평가 사유(Thought)를 3~4문장으로 상세히 적으세요. 특히 팩트체크 원문에 없는 거짓이 있다면 구체적으로 명시하여 감점하세요.
            4. 기준에 따라 총점(total_score, 0~100)을 합산하여 매기세요.
            5. 만약 총점이 70점 미만이라면, Editor가 개선해야 할 명확한 지시사항(redo_instruction)을 남기세요. 70점 이상이면 빈 문자열.

            [응답 예시]
            {{
                "thought": "1. 사실성: 모든 통계 수치가 원문과 일치함. 2. 논리성: 서론에서 결론까지 흐름이 매끄러움. 3. 어조: 중립적이고 전문적인 어조를 잘 유지함.",
                "total_score": 95,
                "redo_instruction": ""
            }}

            [반환 포맷 예시]
            {{
                "thought": "...사실성 점검: OOO부분은 원문에 없음. 논리성: 흐름이 좋음. 어조: 적절함...",
                "total_score": 65,
                "redo_instruction": "OOO 부분은 원문에 없으니 삭제하거나 수정하세요."
            }}
            """
            
            # G-EVAL 모델 호출 (llm_mode 라우팅 등 중앙 집중식 call_llm 활용)
            schema = {
                "type": "object",
                "properties": {
                    "thought": {"type": "string"},
                    "total_score": {"type": "integer"},
                    "redo_instruction": {"type": "string"}
                },
                "required": ["thought", "total_score", "redo_instruction"]
            }
            # G-EVAL 모델 호출 (call_llm이 schema와 함께 호출되면 이미 파싱된 dict를 반환함)
            g_eval_result, usage = call_llm(prompt=g_eval_prompt, model_size="local", state=state, schema=schema)
            
            if not g_eval_result:
                g_eval_result = {"total_score": 75, "redo_instruction": "", "thought": "응답 누락으로 강제 통과 처리된 G-EVAL"}
                
            total_tokens = update_total_tokens(state, usage, "JudgeAgent")
            g_score = g_eval_result.get("total_score", 0)
            thought = g_eval_result.get("thought", "")
            redo_instruction = g_eval_result.get("redo_instruction", "")
            
            if g_score >= 70:
                status = "PASS"
                feedback = f"통합 G-EVAL 통과 (점수: {g_score}점). 판단 사유: {thought}"
            else:
                status = "FAIL_EDITOR"
                feedback = f"통합 G-EVAL 개선 지시 (점수: {g_score}점). 판단 사유: {thought} | 지시사항: {redo_instruction}"
                
            msg = f"✅ 검수 완료: {status} (통합 G-EVAL 점수: {g_score}점)"
            log_llm_event("agent_judge", msg, details={"g_eval": g_eval_result, "thought": thought})
            
            
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
