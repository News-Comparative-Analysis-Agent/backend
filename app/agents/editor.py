from app.agents.state import ComparisonState
from app.agents.utils import update_total_tokens
from app.core.logger import logger, log_llm_event
from langsmith import traceable
import json
import os
import traceback

class EditorAgent:
    """
    Agent 4) Editor Agent (표현/중복/톤 정리)
    • 입력: JSON Outline 초안
    • 출력: 최종 JSON 문서 (에디팅 로그 포함)
    • 제한: 새 사실 추가 금지(근거 밖 생성 금지)
    """
    def __init__(self):
        pass

    @traceable(name="Agent 4: Editor (비평 기사 최종 교정) 🎨")
    def node_edit_draft(self, state: ComparisonState) -> dict:
        """
        [Node] Writer가 작성한 비평 기사 본문을 다듬고 톤을 일관되게 정리합니다.
        문맥의 흐름을 개선하고 오탈자나 어색한 표현을 교정합니다.
        """
        draft = state.get("draft_article")
        issue_id = state.get("issue_id") or (draft.get("issue_id") if isinstance(draft, dict) else None)
        
        judge_status = state.get("judge_status", "")
        judge_feedback = state.get("judge_feedback", "")
        retry_count = state.get("retry_count", 0)
        llm_mode = state.get("llm_mode", "gemini_only")
        
        log_llm_event("agent_editor", f"Agent 4 (Editor): 비평 기사 최종 교정 시작 (Retry: {retry_count})")
        
        try:
            issue_id_int = int(issue_id) if issue_id is not None else 0
        except (ValueError, TypeError):
            issue_id_int = 0
            
        prompt = f"""
        당신은 신문사의 베테랑 데스크 에디터입니다.
        작성된 비평 기사 초안을 읽고 문맥의 흐름, 문법, 표현의 적절성, 톤앤매너를 전문적으로 교정하십시오.

        [비평 기사 초안 (JSON)]
        {json.dumps(draft, ensure_ascii=False, indent=2) if isinstance(draft, dict) else draft}

        [에디팅 가이드라인 🚨]
        1. **가독성 개선**: 본문(article_body)의 문장 흐름을 매끄럽게 다듬고, 불필요하게 긴 문장은 간결하게 수정하되 의미는 보존하십시오.
        2. **전문성 강화**: 논설 위원의 품격에 맞는 정중하고 객관적인 문체를 유지하십시오.
        3. **무결성 유지**: 새로운 사실, 수치, 출처를 절대 추가하거나 삭제하지 마십시오.
        4. **일관성 확보**: 제목(title)과 본문의 내용이 완벽하게 일치하는지 확인하십시오.

        [출력 JSON 스키마]
        {{
          "issue_id": {issue_id_int},
          "title": "교정된 기사 제목",
          "description": "교정된 이슈 요약",
          "background": "교정된 사건 배경",
          "core_contentions": "교정된 핵심 쟁점",
          "conflict_summary": "교정된 언론사 시각 차이 요약",
          "media_views": [
            {{
              "press": "언론사명",
              "claim": "교정된 핵심 주장",
              "evidence": "원문 인용구(수정 금지)",
              "url": "기사 URL(수정 금지)",
              "narrative": "교정된 분석 문장"
            }}
          ],
          "article_body": "최종 교정된 비평 기사 본문"
        }}
        """
        
        # 이전 Judge 단계에서 Editor를 향한 사소한 피드백이 있다면 반영
        if judge_status == "FAIL_EDITOR" and judge_feedback:
            previous_edit = state.get("edited_article", "")
            prompt += f"""
            
            [🚨 편집장 최종 수정 지시 🚨]
            {judge_feedback}
            
            [이전 교정본]
            {json.dumps(previous_edit, ensure_ascii=False) if isinstance(previous_edit, dict) else previous_edit}
            """
            
        try:
            if llm_mode == "gemini_only":
                import google.generativeai as genai
                response_schema = {
                    "type": "object",
                    "properties": {
                        "issue_id": {"type": "integer"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "background": {"type": "string"},
                        "core_contentions": {"type": "string"},
                        "conflict_summary": {"type": "string"},
                        "media_views": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "press": {"type": "string"},
                                    "claim": {"type": "string"},
                                    "evidence": {"type": "string"},
                                    "url": {"type": "string"},
                                    "narrative": {"type": "string"},
                                },
                                "required": ["press", "claim", "evidence", "url", "narrative"],
                            },
                        },
                        "article_body": {"type": "string"}
                    },
                    "required": [
                        "issue_id", "title", "description", "background", "core_contentions", 
                        "conflict_summary", "media_views", "article_body"
                    ],
                }
                gen_model = genai.GenerativeModel(
                    'gemini-2.0-flash',
                    generation_config={"response_mime_type": "application/json", "response_schema": response_schema},
                )
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
                edited_article = final_data
                log_llm_event("agent_editor", "비평 기사 교정 완료", details=edited_article)
            else:
                edited_article = {"title": "오류: JSON 파싱 실패", "content": final_data}
                log_llm_event("agent_editor", "비평 기사 교정 실패 (파싱 오류)", details=str(final_data))
                
            return {
                "edited_article": edited_article, 
                "messages": ["표현 및 중복 톤 정리 완료"],
                "total_tokens": total_tokens
            }
            
        except Exception as e:
            msg = f"에디팅 실패: {e}"
            logger.error(f"🎨 [EditorAgent] {msg}")
            traceback.print_exc()
            return {"edited_article": draft, "messages": [msg]}
