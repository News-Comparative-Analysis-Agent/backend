from app.agents.state import ComparisonState
from app.agents.utils import call_local_llm, update_total_tokens
from app.core.logger import logger, log_llm_event

class EditorAgent:
    """
    Agent 4) Editor Agent (표현/중복/톤 정리)
    • 입력: 초안
    • 출력: 수정 초안 + 수정 로그
    • 제한: 새 사실 추가 금지(근거 밖 생성 금지)
    """
    def __init__(self):
        pass

    def node_edit_draft(self, state: ComparisonState) -> dict:
        """
        [Node] Writer가 작성한 초안을 다듬고 톤을 일관되게 정리합니다.
        가짜 정보(새로운 스탯, 없는 매체)를 지어내서는 안 됩니다.
        """
        draft = state.get("draft_article", "")
        judge_status = state.get("judge_status", "")
        judge_feedback = state.get("judge_feedback", "")
        retry_count = state.get("retry_count", 0)
        llm_mode = state.get("llm_mode", "local_priority")
        
        msg_start = f"Agent 4 (Editor): 초안 교정 시작 (Mode: {llm_mode}, Retry: {retry_count})"
        logger.info(f"🎨 [EditorAgent] {msg_start}")
        
        if not draft or "오류가 발생" in draft:
            logger.warning("🎨 [EditorAgent] 전송된 초안이 없어 교정을 생략합니다.")
            return {"edited_article": draft, "edit_log": "전송된 초안이 없어 교정을 생략합니다.", "messages": ["에디터 패스"]}
            
        prompt = f"""
        당신은 프로페셔널한 신문사 데스크톱 에디터입니다.
        아래 기자의 초안을 읽고 문맥의 흐름, 문법, 표현의 중복, 언론사 톤앤매너를 깔끔하게 교정하십시오.
        
        [기자 초안]
        {draft}
        
        [에디팅 제한 및 규칙 🚨]
        1. **새로운 사실, 통계, 출처 매체를 절대 지어내거나 추가하지 마십시오.** 오직 문장 표현만 다듬습니다.
        2. 원본 초안에 있던 **근거(출처 링크)** 포맷은 절대 훼손하거나 지우지 말고 그대로 유지하십시오.
        3. 결과물은 반드시 아래와 같이 [수정 로그] 구역과 [최종 수정 초안] 구역을 나누어 출력하십시오.
        
        [출력 형식 가이드]
        ## 수정 로그
        (어떤 톤을 어떻게 다루었고, 어떤 중복 표현을 다듬었는지 2~3줄로 요약)
        
        ## 최종 수정 초안
        (수정된 마크다운 기사 전체)
        """
        
        # 이전 Judge 단계에서 Editor를 향한 사소한 피드백이 있다면 반영
        if judge_status == "FAIL_EDITOR" and judge_feedback:
            previous_edit = state.get("edited_article", "")
            prompt += f"""
            
            [🚨 이전 발행 검토 피드백 반영 (데스크 지시) 🚨]
            편집장(Judge)으로부터 문장 톤이나 중복에 관한 지시가 내려왔습니다.
            본인이 교정했던 [이전 수정본]을 확인하고, 지시 사항을 반영하여 재교정하십시오.
            
            수정 지시: {judge_feedback}
            
            [본인이 교정했던 이전 수정본]
            {previous_edit}
            """
            log_llm_event("agent_editor", f"Editor 피드백 반영 및 재교정 모드 활성화")
            
        try:
            if llm_mode == "gemini_only":
                import google.generativeai as genai
                gen_model = genai.GenerativeModel('gemini-2.0-flash')
                response = gen_model.generate_content(prompt)
                final_text = response.text
                usage = {
                    "prompt_tokens": len(prompt) // 4,
                    "completion_tokens": len(final_text) // 4
                }
            else:
                final_text, usage = call_local_llm("7B_2", prompt)
            
            # 토큰 업데이트
            total_tokens = update_total_tokens(state, usage)

            # 수정 로그와 기사 본문을 파싱 (단순 split 활용)
            parts = final_text.split("## 최종 수정 초안")
            if len(parts) == 2:
                edit_log = parts[0].replace("## 수정 로그", "").strip()
                edited_article = parts[1].strip()
            else:
                edit_log = "파싱 실패 - 전체 수정 내역 기록 불가"
                edited_article = final_text.strip()
                
            msg = "표현 및 중복 톤 정리 완료"
            logger.success(f"🎨 [EditorAgent] {msg}")
            log_llm_event("agent_editor", msg, details=final_text)
            
            return {
                "edited_article": edited_article, 
                "edit_log": edit_log, 
                "messages": [msg],
                "total_tokens": total_tokens
            }
            
        except Exception as e:
            msg = f"에디팅 실패: {e}"
            logger.error(f"🎨 [EditorAgent] {msg}")
            return {"edited_article": draft, "edit_log": msg, "messages": [msg]}
