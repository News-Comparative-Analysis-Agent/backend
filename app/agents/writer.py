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

    @traceable(name="Agent 3: Writer (초안 구조 생성) ✍️")
    def node_write_draft(self, state: ComparisonState) -> dict:
        """
        [Node] 구조화된 쟁점과 근거 데이터를 바탕으로 기사 초안을 작성합니다.
        Judge의 피드백이 있다면 이를 반영하여 다시 작성합니다.
        """
        structured_issues = state.get("structured_issues", [])
        judge_feedback = state.get("judge_feedback", "")
        judge_status = state.get("judge_status", "")
        retry_count = state.get("retry_count", 0)
        
        log_llm_event("agent_writer", f"Agent 3 (Writer): 비평 초안 작성 시작 (Retry: {retry_count})")
        
        if not structured_issues:
            return {"draft_article": "구조화된 쟁점 데이터가 없어 작성을 진행할 수 없습니다.", "messages": ["쟁점 부재로 Writer 중단"]}
            
        issues_json = json.dumps(structured_issues, ensure_ascii=False, indent=2)
        
        prompt = f"""
        당신은 수석 논설위원입니다. 다음은 여러 언론사들의 관점 차이를 정리한 '핵심 쟁점(Issue)' 데이터입니다.
        이를 바탕으로 저성능 LLM의 환각을 방지하기 위한 '데이터 기반 기사 개요(Outline)'를 작성하세요.
        
        [쟁점 데이터 목록]
        {issues_json}
        
        [필수 사항]
        본문을 서술하지 마시고, 제공된 JSON 스키마에 맞추어 항목별 핵심을 요약(정리)하십시오.
        새로운 주장을 지어내지 말고 쟁점 데이터 안에 있는 팩트와 출처(claim, evidence, url)만 재배치하십시오.
        
        [출력 JSON 구조]
        {{
          "title": "전체 기사 제목",
          "introduction": {{
            "context": "이슈 맥락",
            "background": "사건 배경"
          }},
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
                  "argument_summary": "해당 매체의 관점 요약"
                }}
              ]
            }}
          ],
          "summary": "전체 결론 요약"
        }}
        """
        
        # 이전 Judge 단계에서 Writer를 향한 반려 사유가 있다면 프롬프트에 추가
        if judge_status == "FAIL_WRITER" and judge_feedback:
            previous_draft = state.get("draft_article", "")
            prompt += f"""
            
            [🚨 이전 초안 검토 피드백 반영 필수 🚨]
            편집장(Judge)으로부터 다음과 같은 피드백이 도착했습니다. 
            아래 당신이 작성했던 [이전 초안]을 확인하고, 피드백 내용에 맞추어 초안을 전면 수정하십시오.
            
            [피드백 내용]
            {judge_feedback}
            
            [당신이 작성했던 이전 JSON 초안]
            {json.dumps(previous_draft, ensure_ascii=False) if isinstance(previous_draft, dict) else previous_draft}
            """
            log_llm_event("agent_writer", f"Writer 피드백 반영 및 자가 수정 모드 활성화")
            
        try:
            # call_llm은 (data, usage)를 반환함. Writer는 텍스트 생성이므로 data가 문자열로 반환될 수 있음.
            # 하지만 utils.call_llm은 내부적으로 parse_llm_json을 호출하므로, 
            # 텍스트 생성의 경우 JSON이 아니라면 call_local_llm을 직접 쓰거나 utils를 보강해야 함.
            # 여기서는 텍스트 생성을 위해 call_llm이 아닌 직접 호출 방식을 유지하되 토큰만 추합.
            
            llm_mode = state.get("llm_mode", "gemini_only")
            if llm_mode == "gemini_only":
                import google.generativeai as genai
                response_schema = {
                    "type": "OBJECT",
                    "properties": {
                        "title": {"type": "STRING"},
                        "introduction": {
                            "type": "OBJECT",
                            "properties": {
                                "context": {"type": "STRING"},
                                "background": {"type": "STRING"}
                            },
                            "required": ["context", "background"]
                        },
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
                                                "argument_summary": {"type": "STRING"}
                                            },
                                            "required": ["press", "claim", "evidence", "url", "argument_summary"]
                                        }
                                    }
                                },
                                "required": ["contention_title", "conflict_summary", "media_views"]
                            }
                        },
                        "summary": {"type": "STRING"}
                    },
                    "required": ["title", "introduction", "contentions", "summary"]
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
                final_data, usage = call_llm(prompt, "7B_2", state)
                
            # 토큰 업데이트
            total_tokens = update_total_tokens(state, usage)

            msg = "비평 보고서 개요(Outline JSON) 생성 완료"
            log_llm_event("agent_writer", msg)
            if isinstance(final_data, dict):
                logger.info(f"✍️ [WriterAgent] 생성된 초안 제목: {final_data.get('title', '제목 없음')}")
            return {"draft_article": final_data, "messages": [msg], "total_tokens": total_tokens}
            
        except Exception as e:
            msg = f"초안 생성 실패: {e}"
            logger.error(msg)
            log_llm_event("agent_writer", msg)
            return {"draft_article": "보고서 생성 중 오류가 발생했습니다.", "messages": [msg]}
