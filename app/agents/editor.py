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
    def __init__(self, db=None):
        self.db = db

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
        1. 모든 필드(title, description, article_body 등)는 **반드시 한국어로만 작성**해야 합니다. 절대 중국어나 다른 외국어를 사용하지 마세요.
        2. **가독성 개선**: 본문(article_body)의 문장 흐름을 매끄럽게 다듬고, 불필요하게 긴 문장은 간결하게 수정하되 의미는 보존하십시오.
        3. **전문성 강화**: 논설 위원의 품격에 맞는 정중하고 객관적인 문체를 유지하십시오.
        4. **무결성 유지**: 새로운 사실, 수치, 출처를 절대 추가하거나 삭제하지 마십시오.
        5. **일관성 확보**: 제목(title)과 본문의 내용이 완벽하게 일치하는지 확인하십시오.

        [응답 예시]
        {{
          "issue_id": {issue_id_int},
          "title": "의료계 집단 행동과 정부의 대응",
          "description": "정부의 의대 증원 정책에 반발한 전공의들의 집단 사직으로 의료 현장의 혼란이 가중되고 있습니다.",
          "background": "정부가 필수 의료 인력 부족 문제를 해결하기 위해 의과대학 정원을 2,000명 늘리겠다고 발표했습니다.",
          "core_contentions": "정부는 증원을 통한 의료 개혁을, 의료계는 졸속 행정이라며 철회를 주장하고 있습니다.",
          "conflict_summary": "보수 언론은 환자 안전을 최우선으로 집단 행동 자제를 촉구하고, 진보 언론은 정부의 불통 행정을 지적하며 대협상을 요구하고 있습니다.",
          "media_views": [
            {{
              "press": "...", "claim": "...", "evidence": "...", "url": "...", "narrative": "..."
            }}
          ],
          "article_body": "정부와 의료계의 강대강 대치가 길어지면서 국민들의 불안이 임계점에 도달하고 있다... (이하 교정된 한국어 본문)"
        }}

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
            
        # LLM 호출
        try:
            # 7B 모델의 경우 스키마 준수율을 높이기 위해 명시적으로 스키마 예시를 한 번 더 강조
            modified_prompt = prompt + "\n※ 주의: 반드시 위 [출력 JSON 스키마]의 모든 필드(title, description, article_body 등)를 포함한 하나의 JSON 객체만 반환하세요."

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
                # 7B 모델 호출 시 schema를 직접 전달하여 utils.py의 response_format 기능을 활성화
                fallback_schema = {
                    "issue_id": issue_id_int,
                    "title": state.get("title", ""),
                    "description": state.get("description", ""),
                    "background": state.get("background", ""),
                    "media_views": state.get("media_views", []),
                    "article_body": "교정된 본문"
                }
                final_data, usage = call_llm(modified_prompt, "7B", state, schema=fallback_schema)
            
            # 토큰 업데이트
            total_tokens = update_total_tokens(state, usage, "EditorAgent")

            # 데이터 보정 (7B 모델이 일부 필드만 반환했을 경우 복구)
            if not isinstance(final_data, dict):
                final_data = {"article_body": str(final_data)}
            
            # 필수 필드 복구 로직 (이전 단계인 draft나 state에서 가져옴)
            final_data.setdefault("issue_id", issue_id_int)
            final_data.setdefault("title", state.get("title") or (draft.get("title") if isinstance(draft, dict) else "제목 없음"))
            final_data.setdefault("description", state.get("description") or (draft.get("description") if isinstance(draft, dict) else "설명 없음"))
            final_data.setdefault("background", state.get("background") or (draft.get("background") if isinstance(draft, dict) else ""))
            final_data.setdefault("core_contentions", state.get("core_contentions") or (draft.get("core_contentions") if isinstance(draft, dict) else ""))
            final_data.setdefault("conflict_summary", state.get("conflict_summary") or (draft.get("conflict_summary") if isinstance(draft, dict) else ""))
            final_data.setdefault("media_views", state.get("media_views") or (draft.get("media_views") if isinstance(draft, dict) else []))
            
            if "article_body" not in final_data:
                 # 본문이 없을 경우 draft의 본문을 그대로 사용
                 final_data["article_body"] = draft.get("article_body") if isinstance(draft, dict) else str(draft)

            edited_article = final_data
            log_llm_event("agent_editor", "비평 기사 교정 완료", details=json.dumps(edited_article, ensure_ascii=False, indent=2))
                
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
