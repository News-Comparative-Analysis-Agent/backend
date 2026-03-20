import json
from app.agents.state import ComparisonState
from app.agents.utils import call_llm, update_total_tokens
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
        1. 단순한 사실 나열이 아닌, 언론사들이 왜 서로 다른 목소리를 내는지, 그 이면에 깔린 핵심 쟁점을 날카롭게 분석하십시오.
        2. 'article_body'는 쟁점의 발단, 전개, 갈등의 핵심, 그리고 사회적 함의를 포함하여 1000자 내외의 완성된 기사 형태로 작성하십시오.
        3. 기존 데이터(title, description, background, conflict_summary 등)는 분석을 위해 활용하되, 필요하다면 더 정교하게 리라이팅하여 최종 JSON에 포함하십시오.
        4. 새로운 사실을 날조하지 마십시오.

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
        
        # 이전 Judge 단계에서 Writer를 향한 반려 사유가 있다면 프롬프트에 추가
        if judge_status == "FAIL_WRITER" and judge_feedback:
            previous_draft = state.get("draft_article", "")
            prompt += f"""
            
            [🚨 편집장 피드백 반영 사항 🚨]
            {judge_feedback}
            
            [당신이 작성했던 이전 초안]
            {json.dumps(previous_draft, ensure_ascii=False) if isinstance(previous_draft, dict) else previous_draft}
            """
            log_llm_event("writer_agent", f"Writer 피드백 반영 및 자가 수정 모드 활성화")
            
        try:
            llm_mode = state.get("llm_mode", "gemini_only")
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
                
                # 생성된 초안을 로그에 출력하도록 추가
                log_llm_event("agent_writer", "Response received", details=response.text)
                
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
            total_tokens = update_total_tokens(state, usage, "WriterAgent")

            msg = "비평 보고서 개요(Outline JSON) 생성 완료"
            log_llm_event("agent_writer", msg, details=json.dumps(final_data, ensure_ascii=False, indent=2))
            return {"draft_article": final_data, "messages": [msg], "total_tokens": total_tokens}
            
        except Exception as e:
            msg = f"초안 생성 실패: {e}"
            logger.error(msg)
            log_llm_event("agent_writer", msg)
            return {"draft_article": "보고서 생성 중 오류가 발생했습니다.", "messages": [msg]}
