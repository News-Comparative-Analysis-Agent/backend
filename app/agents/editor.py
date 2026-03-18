from app.agents.state import ComparisonState
from app.agents.utils import update_total_tokens
from app.core.logger import logger, log_llm_event
from langsmith import traceable
import json

class EditorAgent:
    """
    Agent 4) Editor Agent (표현/중복/톤 정리)
    • 입력: JSON Outline 초안
    • 출력: 최종 JSON 문서 (에디팅 로그 포함)
    • 제한: 새 사실 추가 금지(근거 밖 생성 금지)
    """
    def __init__(self):
        pass

    @traceable(name="Agent 4: Editor (비평 초안 작성) 🎨")
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
        아래 기자의 초기 'JSON 개요(Outline)'를 읽고 문맥의 흐름, 문법, 표현의 중복, 언론사 톤앤매너를 자연스럽게 풀어서 깔끔하게 교정하십시오.
        
        [기자 JSON 개요]
        {json.dumps(draft, ensure_ascii=False, indent=2) if isinstance(draft, dict) else draft}
        
        [에디팅 제한 및 규칙 🚨]
        1. **새로운 사실, 통계, 출처 매체를 절대 지어내거나 추가하지 마십시오.** 오직 문장 표현만 다듬습니다.
        2. 원본 개요에 있던 **근거(출처)** 포맷은 절대 훼손하거나 지우지 말고 그대로 유지하십시오.
        3. 반환값은 반드시 아래의 완성된 JSON 문서 형식이어야 하며, 개요(Outline) 형태가 아니라 문장으로 풀어진 기사 형태(Narrative)를 갖추어야 합니다.
        
        [출력 JSON 구조]
        {{
          "title": "다듬어진 최종 기사 제목",
          "introduction": "개요의 context와 background를 자연스러운 2~3문장 서론으로 결합",
          "contentions": [
            {{
              "contention_title": "쟁점 제목",
              "conflict_summary": "이 쟁점에서의 갈등 요약",
              "media_views": [
                {{
                  "press": "매체명",
                  "claim": "원문 주장",
                  "evidence": "인용구",
                  "url": "기사 URL",
                  "argument_summary": "개요 요약본",
                  "narrative": "기사 본문. 자연스럽게 서술된 매체의 주장과 근거 문장"
                }}
              ]
            }}
          ],
          "summary": "다듬어진 최종 결론 문단",
          "edit_log": "어떤 톤을 어떻게 다루었고, 어떤 중복 표현을 다듬었는지 2~3줄로 요약"
        }}
        """
        
        # 이전 Judge 단계에서 Editor를 향한 사소한 피드백이 있다면 반영
        if judge_status == "FAIL_EDITOR" and judge_feedback:
            previous_edit = state.get("edited_article", "")
            prompt += f"""
            
            [🚨 이전 발행 검토 피드백 반영 (데스크 지시) 🚨]
            편집장(Judge)으로부터 문장 톤이나 중복에 관한 지시가 내려왔습니다.
            본인이 교정했던 [이전 수정본]을 확인하고, 지시 사항을 반영하여 재교정하십시오.
            
            수정 지시: {judge_feedback}
            
            [본인이 교정했던 이전 JSON 수정본]
            {json.dumps(previous_edit, ensure_ascii=False) if isinstance(previous_edit, dict) else previous_edit}
            """
            log_llm_event("agent_editor", f"Editor 피드백 반영 및 재교정 모드 활성화")
            
        try:
            if llm_mode == "gemini_only":
                import google.generativeai as genai
                response_schema = {
                    "type": "OBJECT",
                    "properties": {
                        "title": {"type": "STRING"},
                        "introduction": {"type": "STRING"},
                        "contentions": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "contention_title": {"type": "STRING"},
                                    "conflict_summary": {"type": "STRING"},
                                    "media_views": {
                                        "type": "ARRAY",
                                        "items": {
                                            "type": "OBJECT",
                                            "properties": {
                                                "press": {"type": "STRING"},
                                                "claim": {"type": "STRING"},
                                                "evidence": {"type": "STRING"},
                                                "url": {"type": "STRING"},
                                                "argument_summary": {"type": "STRING"},
                                                "narrative": {"type": "STRING"}
                                            },
                                            "required": ["press", "claim", "evidence", "url", "argument_summary", "narrative"]
                                        }
                                    }
                                },
                                "required": ["contention_title", "conflict_summary", "media_views"]
                            }
                        },
                        "summary": {"type": "STRING"},
                        "edit_log": {"type": "STRING"}
                    },
                    "required": ["title", "introduction", "contentions", "summary", "edit_log"]
                }
                gen_model = genai.GenerativeModel('gemini-2.0-flash', generation_config={"response_mime_type": "application/json", "response_schema": response_schema})
                response = gen_model.generate_content(prompt)
                
                try:
                    final_data = json.loads(response.text)
                except:
                    from app.agents.utils import parse_llm_json
                    final_data = parse_llm_json(response.text)
                
                usage = {
                    "prompt_tokens": len(prompt) // 4,
                    "completion_tokens": len(response.text) // 4
                }
            else:
                from app.agents.utils import call_llm
                final_data, usage = call_llm(prompt, "7B", state)
            
            # 토큰 업데이트
            total_tokens = update_total_tokens(state, usage, "EditorAgent")

            if isinstance(final_data, dict):
                edit_log = final_data.get("edit_log", "에디팅 로그 누락")
                edited_article = final_data
            else:
                edit_log = "파싱 실패 - 전체 수정 내역 기록 불가"
                edited_article = {"title": "오류: JSON 파싱 실패", "content": final_data}
                
            msg = "표현 및 중복 톤 정리 완료"
            logger.success(f"🎨 [EditorAgent] {msg}")
            
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
