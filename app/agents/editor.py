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
            
        # 원본 기사 컨텍스트 구성 (각 300자 발췌)
        articles = state.get("articles", [])
        articles_context = ""
        for i, art in enumerate(articles, 1):
            content_snippet = art.get("content", "")[:300]
            articles_context += f"--- [원본 기사 {i}: {art.get('press', '알수없음')}] ---\n{content_snippet}...\n\n"

        prompt = f"""
        당신은 사안의 횡단적 분석을 전문으로 하는 신문사의 **수석 논설위원**입니다.
        아래 [비평 기사 초안]과 [원본 뉴스 기사 (참조용)]를 정밀하게 대조하며, 단순한 사실 나열을 넘어 사안을 꿰뚫는 통찰력이 담긴 **최종 비평 리포트**로 완성하십시오.

        [비평 기사 초안 (JSON)]
        {json.dumps(draft, ensure_ascii=False, indent=2) if isinstance(draft, dict) else draft}

        [원본 뉴스 기사 (참조용: 각 300자)]
        {articles_context}

        [에디팅 및 집필 가이드라인 (중요! 🖋️)]
        1. **⚠️ 나열 금지 (Anti-Listing)**: 절대로 "A 언론사는..., B 언론사는..." 하는 식으로 언론사를 주어로 삼아 순차적으로 나열하지 마십시오. 이는 하급 기자의 방식입니다.
        2. **쟁점 중심 통합 (Issue-based Synthesis)**: 사안을 관통하는 '핵심 갈등'을 소제목이나 문단의 주제로 잡으십시오. 제공된 '원본 뉴스 기사'에서 초안이 놓친 날카로운 표현이나 구체적인 논조를 찾아내어 본문에 **입체적으로 녹여내십시오.**
        3. **논리적 연결어 사용 강제**: 모든 문장이나 문단 사이에는 반드시 (반면, 또한, 결과적으로, 이와는 대조적으로, 그럼에도 불구하고)와 같은 논리적 연결어를 사용하여 서사가 물 흐르듯 이어지게 하십시오.
        4. **통찰력 있는 제목**: 단순히 사안을 요약하는 제목이 아닌, 사안의 본질적 모순이나 시대적 의미를 짚어주는 압축적인 제목을 만드세요.
        5. **결론부 강화**: 마지막 문단은 반드시 이 논쟁이 우리 사회나 독자에게 주는 시사점이 무엇인지, 수석 논설위원으로서의 날카로운 결론을 한 문장으로 남기십시오.
        6. **무결성 유지**: 문장은 유려하게 고치되, 제공된 원본 데이터에 없는 사실을 날조하는 것은 절대 금지입니다.

        [최종 출력 형식 예시 (JSON)]
        {{
          "issue_id": {issue_id_int},
          "title": "압축적이고 선언적인 제목 (예: '보수의 심장에 던져진 리트머스 시험지')",
          "description": "배경과 갈등을 한눈에 보여주는 심층 요약",
          "background": "구조적 배경",
          "core_contentions": "대립하는 가치의 정점",
          "conflict_summary": "매체 간의 시각 차이를 '대조'와 '대립'의 관점에서 요약",
          "media_views": [
            {{
              "press": "...", "claim": "...", "evidence": "...", "url": "...", "narrative": "..."
            }}
          ],
          "article_body": "원본의 풍부한 맥락을 반영하여 재조직된, 매끄러운 최종 통합 비평 기사 본문"
        }}

        [출력 JSON 스키마]
        {{
          "issue_id": {issue_id_int},
          "title": "통찰력 있는 기사 제목",
          "description": "심층 요약",
          "background": "구조적 배경 설명",
          "core_contentions": "대립하는 핵심 가치",
          "conflict_summary": "언론사별 시각 대조 요약",
          "media_views": [
            {{
              "press": "언론사명",
              "claim": "핵심 주장",
              "evidence": "인용된 근거(수정 금지)",
              "url": "기사 URL(수정 금지)",
              "narrative": "해당 매체의 프레임 분석"
            }}
          ],
          "article_body": "최종 완성된 심층 비평 기사 본문 (원본 대조 및 통찰력 중점)"
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
