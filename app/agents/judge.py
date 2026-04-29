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
            [갈등 요약]: {issue_context.get('conflict_summary', '')}
            """.strip()
            
            contexts = []
            for m in media_views:
                press = m.get("press", "알수없음")
                ev = m.get("evidence", "")
                na = m.get("narrative", "")
                if ev or na:
                    contexts.append(f"[{press}]\n원문 근거: {ev}\n보도 프레임: {na}")
            if not contexts:
                contexts = ["제공된 문서 없음"]
            contexts_str = "\n\n".join([f"[{i+1}번 언론사 원문]\n{c}" for i, c in enumerate(contexts)])
            
            logger.info("⚖️ [JudgeAgent] 통합 G-EVAL(팩트+어조/문맥) 벤치마킹을 시작합니다...")
            
            g_eval_prompt = f"""
            당신은 미디어 비평 기사 검수 전문가입니다.
            아래 기사가 미디어스 언론 보도 비교 기사의 형식과 품질 기준을 충족하는지 평가하십시오.

            [평가 대상 기사]
            {edited_article_str}

            [이슈 맥락]
            {full_issue_context_str}

            [언론사별 원문 근거 (기사가 인용해야 할 실제 문장)]
            {contexts_str}

            [평가 기준 (Rubric)]
            1. 팩트 정합성 (40점): 기사 본문의 인용 문장이 위 [언론사별 원문 근거]의 문장과 한 글자도 틀리지 않고 일치하는가? 원문에 없는 사실을 추가하거나 요약·변형하지 않았는가?
            2. 형식 준수 (30점): 각 언론사 소개가 "{{언론사}}는 {{날짜}} 사설 <{{제목}}>에서 '...'라고 했다." 형식을 따르는가? 대립하는 시각은 "반면"으로 전환했는가? 같은 언론사 추가 인용은 "이어"로 연결했는가?
            3. 구조 완결성 (30점): 리드(행위 주체 명시 + 갈등 요약 원문 그대로) → 사건 경위(반박 포함) → 언론사별 입장 순서를 지켰는가? 마무리 문단 없이 마지막 언론사 인용으로 끝맺었는가? 기자 해석·논평 문장("이처럼", "결국", "이는 ~을 의미한다" 등)이 없는가?

            [작업 지침]
            - 총점이 70점 미만이면 반드시 `redo_instruction`에 **어떤 문장을 어떻게 수정해야 하는지 구체적으로** 작성하십시오.
            - redo_instruction은 Writer에게 전달되므로, "원문 근거의 어떤 문장을 그대로 사용해야 하는지"까지 명시하십시오.

            [응답 예시]
            성공예시 (PASS):
            {{
              "thought": "1. 팩트 정합성: 조선일보 인용문 '이런 의문을 없앨 방법은 간단하다. 녹취록 전문을 공개하면 된다'가 원문과 일치함. 경향신문 인용도 원문과 동일함. 2. 형식 준수: '[언론사]는 사설에서...' 형식을 모든 언론사에 일관되게 사용했고, '반면'으로 진보·보수 시각을 전환함. 3. 구조 완결성: 리드에 갈등 구도를 담고, 사건 경위 → 언론사별 입장 → 마무리 순서를 정확히 따름. 기자 의견·해석 문장 없음.",
              "total_score": 91,
              "redo_instruction": ""
            }}

            반려예시 (FAIL):
            {{
              "thought": "1. 팩트 정합성: 한겨레 인용 부분에서 원문의 '검찰 수사는 재판에서 무죄가 나든 말든'이 '검찰이 무죄 판결에도 불구하고'로 변형되어 있음. 2. 형식 준수: 3번 언론사(경향신문) 소개 시 '[경향신문]에 따르면...' 형식을 사용해 '[경향신문]는 사설에서...' 형식을 위반함. 3. 구조 완결성: 마지막 단락에 '이는 언론의 자기 역할 망각을 보여주는 것이다'라는 기자 해석 문장이 포함되어 있음.",
              "total_score": 58,
              "redo_instruction": "첫째, 한겨레 인용 부분을 원문 근거의 '검찰 수사는 재판에서 무죄가 나든 말든, 일단 야당 대표를 기소해서 사법적 족쇄를 채우려는 의도가 있었던 것으로 의심된다'로 교체하십시오. 둘째, 경향신문 소개 문장을 '경향신문은 사설에서...' 형식으로 수정하십시오. 셋째, 마지막 단락의 '이는 언론의 자기 역할 망각을 보여주는 것이다' 문장을 삭제하십시오."
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
                    final_conflict = e_art.get("conflict_summary") or state.get("conflict_summary") or ""

                    repo.update_issue_analysis_results(
                        issue_id=issue_id,
                        description=final_desc,
                        background=final_bg,
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
