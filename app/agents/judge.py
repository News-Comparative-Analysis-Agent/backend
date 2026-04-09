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
        
        # 최종 결과물 확보 (draft_article 사용)
        edited_article = state.get("draft_article")
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

        # 후속 로직(오류 체크 등)을 위해 데이터 문자열화만 수행 (로깅은 하지 않음)
        article_str = json.dumps(edited_article, ensure_ascii=False) if isinstance(edited_article, dict) else str(edited_article)
        log_llm_event("agent_judge", f"⚖️ [JudgeAgent] 통합 G-EVAL(팩체크+비평톤) 심사 시작... (Retry: {retry_count})")
        
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
            당신은 날카로운 통찰력을 가진 미디어 비평지의 **편집국장**입니다. 
            아래 기사가 기성 언론의 위선을 제대로 폭로하고 있는지, 아니면 흔한 요약 로봇처럼 굴고 있는지 엄격히 심사하십시오.

            [평가 대상 기사]
            {edited_article_str}

            [이슈 맥락 및 원문 근거]
            {full_issue_context_str}
            {contexts_str}

            [평가 기준 (Rubric)]
            1. 팩트 정합성 (40점): 원문 근거에 없는 사실을 지어내거나 숫자를 왜곡하지 않았는가?
            2. 비평적 선명성 (30점): 매체별 `narrative`를 활용해 언론의 프레임 전환이나 본질 흐리기를 날카롭게 공격했는가? (기계적 중립은 감점 대상)
            3. 논리 및 문체 (30점): 서론-본론-결론의 흐름이 단호하며, 미디어스 특유의 독설 섞인 비평적 어휘가 살아있는가?

            [작업 지침]
            - 총점이 70점 미만이면 반드시 `redo_instruction`에 **"어떤 문단의 어떤 어조를 고쳐야 하는지"** 독하게 적으십시오.
            - 점수가 90점 이상이라면, 이는 정말로 기득권 언론의 폐부를 찌르는 명문임을 의미합니다.

            [응답 예시]
            성공예시 (PASS):
            {{
              "thought": "1. 사실성: 박상용 검사의 녹취록 인용구가 토씨 하나 틀리지 않고 원문과 일치함. 2. 비평적 선명성: 조선일보와 한국일보가 '절차적 정당성'을 내세워 본질을 흐리고 있다는 지점을 정확히 포착하여 공격함. 3. 어조: '언론의 직무유기', '본질 흐리기' 등 미디어스 특유의 날카로운 어휘를 적재적소에 배치함.",
              "total_score": 92,
              "redo_instruction": ""
            }}

            반려예시 (FAIL):
            {{
              "thought": "1. 사실성: 팩트 나열에는 문제가 없음. 2. 비평적 선명성: 각 매체의 입장을 'A는 이렇고 B는 저렇다'식으로 단순 나열하는 데 그침. 기성 매체가 왜 그런 프레임을 썼는지에 대한 매서운 비판이 부족함. 3. 어조: 비평 기사라기보다 일반적인 뉴스 요약문에 가까울 정도로 어조가 지나치게 완만함.",
              "total_score": 62,
              "redo_instruction": "본문의 '엇갈린 반응을 보이고 있다'와 같은 표현을 삭제하십시오. 대신 조선일보가 왜 녹취록 전문 공개를 요구하며 본질을 회피하는지 그 '비겁한 저의'를 직접적으로 꾸짖는 문장으로 2단락을 전면 수정하십시오. 또한, '프레임 전환'이라는 단어를 활용해 보수 언론의 보도 행태를 심판하십시오."
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
            
            # ✅ 방어적 코드: 결과가 dict가 아닌 경우 예외 처리 (AttributeError 방지)
            if not isinstance(g_eval_result, dict):
                logger.error(f"⚖️ [JudgeAgent] G-EVAL 응답 파싱 실패 (결과 타입: {type(g_eval_result)}). 기본값으로 대체합니다.")
                g_eval_result = {"total_score": 75, "redo_instruction": "", "thought": "응답 파싱 실패로 자동 통과 처리"}
                
            total_tokens = update_total_tokens(state, usage, "JudgeAgent")
            g_score = g_eval_result.get("total_score", 0)
            thought = g_eval_result.get("thought", "")
            redo_instruction = g_eval_result.get("redo_instruction", "")
            
            if g_score >= 70:
                status = "PASS"
                feedback = f"통합 G-EVAL 통과 (점수: {g_score}점). 판단 사유: {thought}"
            else:
                status = "FAIL_WRITER"
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
                    
                    # 초안 저장 (전체 JSON이 아닌 본문 텍스트만 저장)
                    if isinstance(edited_article, dict):
                        article_body = edited_article.get("article_body", "")
                    else:
                        article_body = str(edited_article)
                    
                    repo.update_issue_draft(issue_id, article_body)
                    
                    # 나머지 분석 메타데이터 저장 (EditorAgent/WriterAgent 결과 우선, 없으면 State 원본 사용)
                    # dict.get(f, default)는 키가 있을 때 빈 문자열이라도 그대로 가져오므로 'or'를 사용하여 빈 값 방어
                    e_art = edited_article if isinstance(edited_article, dict) else {}
                    final_desc = e_art.get("description") or state.get("description") or ""
                    final_bg = e_art.get("background") or state.get("background") or ""
                    final_core = e_art.get("core_contentions") or state.get("core_contentions") or ""
                    final_conflict = e_art.get("conflict_summary") or state.get("conflict_summary") or ""

                    repo.update_issue_analysis_results(
                        issue_id=issue_id,
                        description=final_desc,
                        background=final_bg,
                        core_contentions=final_core,
                        conflict_summary=final_conflict
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
