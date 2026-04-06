import json
from app.agents.state import ComparisonState
from app.agents.utils import update_total_tokens
from app.core.logger import logger, log_llm_event
from langsmith import traceable

class WriterAgent:
    """
    Agent 3) Writer Agent (비평 기사 구조화 초안 생성)
    • 입력: 쟁점 구조 + 근거
    • 출력: JSON 형태의 기사 Outline (v2.0 명세)
      o title, introduction(context/background)
      o contentions (매체별 argument_summary 포함)
      o summary
    • 필수 규칙: 기존 Markdown 출력이 아닌 구조화된 JSON 응답.
    """
    def __init__(self):
        pass

    @traceable(name="Agent 3: Writer (비평 기사 본문 작성) ✍️")
    def node_write_draft(self, state: ComparisonState) -> dict:
        """
        [Node] 구조화된 쟁점과 근거 데이터를 바탕으로 최종 비평 기사 본문을 작성합니다.
        Judge의 피드백이 있다면 이를 반영하여 다시 작성합니다.
        """
        issue_id = state.get("issue_id")
        title = state.get("title", "")
        description = state.get("description", "")
        background = state.get("background", "")
        conflict_summary = state.get("conflict_summary", "")
        media_views = state.get("media_views", [])
        
        judge_feedback = state.get("judge_feedback", "")
        judge_status = state.get("judge_status", "")
        retry_count = state.get("retry_count", 0)
        
        log_llm_event("agent_writer", f"Agent 3 (Writer): 비평 기사 본문 작성 시작 (Retry: {retry_count})")
        
        if not title and not media_views:
            return {"draft_article": "입력 데이터가 부족하여 작성을 진행할 수 없습니다.", "messages": ["데이터 부재로 Writer 중단"]}

        # LLM에게 전달할 컨텍스트 조립
        context = {
            "title": title,
            "description": description,
            "background": background,
            "conflict_summary": conflict_summary,
            "media_views": media_views
        }
        context_json = json.dumps(context, ensure_ascii=False, indent=2)
        
        prompt = f"""
        당신은 수석 논설위원입니다. 
        제공된 언론사별 시각 차이 및 갈등 데이터를 바탕으로, 독자들에게 깊이 있는 통찰을 줄 수 있는 '최종 비평 기사 본문(article_body)'을 작성하세요.

        [분석 데이터]
        {context_json}

        [작성 지침]
        1. 모든 응답(title, article_body 등 모든 필드)은 **반드시 한국어로만 작성**해야 합니다. 절대 중국어나 다른 외국어를 사용하지 마세요.
        2. 단순한 사실 나열이 아닌, 언론사들이 왜 서로 다른 목소리를 내는지, 그 이면에 깔린 핵심 쟁점을 날카롭게 분석하십시오.
        3. 'article_body'는 쟁점의 발단, 전개, 갈등의 핵심, 그리고 사회적 함의를 포함하여 1000자 내외의 완성된 기사 형태로 작성하십시오.
        4. 기존 데이터(title, description, background, conflict_summary 등)는 분석을 위해 활용하되, 필요하다면 더 정교하게 리라이팅하여 최종 JSON에 포함하십시오.
        5. 새로운 사실을 날조하지 마십시오.

        [응답 예시]
        {{
          "title": "의료 대란 기로에 선 대한민국",
          "description": "정부의 의대 증원 강행과 의료계의 집단 사직이 맞물리며 국가적 의료 공백 위기가 고조되고 있습니다.",
          "background": "정부가 필수 의료 인력 확충을 위해 의대 정원을 확대하겠다고 발표한 이후 갈등이 촉발되었습니다.",
          "core_contentions": "정부의 법과 원칙 준수 강조와 의료계의 정책 철회 요구가 평행선을 달리고 있습니다.",
          "conflict_summary": "보수 언론은 환자의 생명을 담보로 한 집단 행동을 비판하며 법적 대응을 지지하는 반면, 진보 언론은 정부의 일방적인 불통 행정이 사태를 악화시켰다고 지적하고 있습니다.",
          "media_views": [
            {{
              "press": "관련 언론사",
              "claim": "...",
              "evidence": "...",
              "url": "...",
              "narrative": "..."
            }}
          ],
          "article_body": "의료계의 겨울이 길어지고 있다... (이하 한국어 기사 본문)"
        }}

        [출력 JSON 스키마]
        {{
          "issue_id": {issue_id},
          "title": "15자 이내의 함축적인 기사 제목",
          "description": "이슈의 배경과 핵심 내용 (3~4문장 요약)",
          "background": "이슈 발생의 결정적 발단 (1~2문장)",
          "core_contentions": "주요 쟁점 사항 (1문장 요약)",
          "conflict_summary": "언론사별 시각 차이 핵심 요약",
          "media_views": [
            {{
              "press": "언론사명",
              "claim": "핵심 주장",
              "evidence": "원문 인용구",
              "url": "기사 URL",
              "narrative": "매체별 서술형 분석"
            }}
          ],
          "article_body": "작성된 최종 비평 기사 본문 내용"
        }}
        """
        

        # LLM 호출
        try:
            llm_mode = state.get("llm_mode", "gemini_only")
            
            # 7B 모델의 경우 스키마 준수율을 높이기 위해 명시적으로 스키마 예시를 한 번 더 강조
            modified_prompt = prompt + "\n※ 주의: 반드시 위 [출력 JSON 스키마]의 모든 필드(title, description, article_body 등)를 포함한 하나의 JSON 객체만 반환하세요."

            if llm_mode == "gemini_only":
                import google.generativeai as genai
                response_schema = {
                    "type": "OBJECT",
                    "properties": {
                        "issue_id": {"type": "INTEGER"},
                        "title": {"type": "STRING"},
                        "description": {"type": "STRING"},
                        "background": {"type": "STRING"},
                        "core_contentions": {"type": "STRING"},
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
                                    "narrative": {"type": "STRING"}
                                },
                                "required": ["press", "claim", "evidence", "url", "narrative"]
                            }
                        },
                        "article_body": {"type": "STRING"}
                    },
                    "required": ["issue_id", "title", "description", "background", "core_contentions", "conflict_summary", "media_views", "article_body"]
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
                # 7B 모델 호출 시 schema를 직접 전달하여 utils.py의 response_format 기능을 활성화
                fallback_schema = {
                    "issue_id": issue_id,
                    "title": title,
                    "description": description,
                    "background": background,
                    "media_views": media_views,
                    "article_body": "비평 본문"
                }
                final_data, usage = call_llm(modified_prompt, "local", state, schema=fallback_schema)
            
            # 데이터 보정 (7B 모델이 일부 필드만 반환했을 경우 입력값으로 복구)
            if not isinstance(final_data, dict):
                final_data = {"article_body": str(final_data)}
            
            # 필수 필드 복구 로직
            if "article_body" not in final_data and "narrative" in final_data:
                # 모델이 media_view 형태만 반환한 경우를 대비해 narrative를 본문으로 차용
                final_data["article_body"] = final_data.get("narrative", "")
            
            final_data.setdefault("issue_id", issue_id)
            final_data.setdefault("title", title or "제목 없음")
            final_data.setdefault("description", description or "설명 없음")
            final_data.setdefault("background", background or "")
            final_data.setdefault("core_contentions", state.get("core_contentions", ""))
            final_data.setdefault("conflict_summary", conflict_summary or "")
            final_data.setdefault("media_views", media_views)
            final_data.setdefault("article_body", "본문 생성에 실패했습니다.")

            # 토큰 업데이트
            total_tokens = update_total_tokens(state, usage, "WriterAgent")

            msg = "비평 보고서 개요(Outline JSON) 생성 완료"
            log_llm_event("agent_writer", msg, details=json.dumps(final_data, ensure_ascii=False, indent=2))
            return {
                "draft_article": final_data, 
                "title": final_data["title"],
                "description": final_data["description"],
                "background": final_data["background"],
                "core_contentions": final_data["core_contentions"],
                "conflict_summary": final_data["conflict_summary"],
                "media_views": final_data["media_views"],
                "messages": [msg], 
                "total_tokens": total_tokens
            }   
            
        except Exception as e:
            msg = f"초안 생성 실패: {e}"
            logger.error(msg)
            log_llm_event("agent_writer", msg)
            return {"draft_article": "보고서 생성 중 오류가 발생했습니다.", "messages": [msg]}
