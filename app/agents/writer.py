import json
from app.agents.state import ComparisonState
from app.agents.utils import call_llm, update_total_tokens
from app.core.logger import logger, log_llm_event
from langsmith import traceable

class WriterAgent:
    """
    Agent 3) Writer Agent (비평 기사 구조화 초안 생성)
    • 입력: 쟁점 구조 + 근거
    • 출력: JSON 형태의 기사 Outline
    """
    def __init__(self):
        pass

    @traceable(name="Agent 3: Writer (비평 기사 본문 작성) ✍️")
    def node_write_draft(self, state: ComparisonState) -> dict:
        """
        [Node] 구조화된 쟁점과 근거 데이터를 바탕으로 최종 비평 기사 본문을 작성합니다.
        LLM은 본문과 제목 작성에만 집중하며, 나머지 데이터는 코드 레벨에서 조립합니다.
        """
        issue_id = state.get("issue_id")
        title = state.get("title", "")
        description = state.get("description", "")
        background = state.get("background", "")
        conflict_summary = state.get("conflict_summary", "")
        media_views = state.get("media_views", [])
        
        retry_count = state.get("retry_count", 0)
        log_llm_event("agent_writer", f"Agent 3 (Writer): 비평 기사 본문 작성 시작 (Retry: {retry_count})")
        
        if not title and not media_views:
            return {"draft_article": {"article_body": "입력 데이터가 부족합니다."}, "messages": ["데이터 부재로 Writer 중단"]}

        # 1. LLM 컨텍스트 조립
        context = {
            "title": title,
            "description": description,
            "background": background,
            "conflict_summary": conflict_summary,
            "media_views": media_views
        }
        context_json = json.dumps(context, ensure_ascii=False, indent=2)
        
        prompt = f"""
        당신은 기득권 언론의 위선과 프레임 전쟁을 폭로하는 **미디어 비평지 '미디어스'의 수석 논설위원**입니다. 
        단순히 사실을 요약하는 AI의 한계를 넘어, 언론이 진실을 어떻게 가공하고 왜곡하는지 송곳처럼 날카롭게 파고드는 '최종 비평 기사'를 작성하십시오.

        [분석 데이터]
        {context_json}

        [작성 지침 - 미디어스 스타일 가이드]
        1. **중립의 함정 탈출**: "엇갈린 반응", "관심이 필요하다"와 같은 기계적 중립 표현을 철저히 배제하십시오. 대신 "본질 흐리기", "프레임 덧씌우기", "받아쓰기 관행" 등 언론의 직무유기를 꾸짖는 용어를 사용하십시오.
        2. **논리의 전개**: 
           - **서론**: 해당 이슈를 다루는 언론 보도 행태의 전반적인 한계점을 지적하며 포문을 여십시오.
           - **본론**: `media_views`의 `narrative`를 활용하여, 보수와 진보 언론이 각각 어떤 프레임으로 사건을 '세탁'하거나 '부각'하는지 날카롭게 대조하십시오.
           - **결론**: 언론이 권력 감시라는 본연의 기능을 상실했을 때 우리 사회가 마주할 비극을 경고하며 끝맺으십시오.
        3. 모든 문장은 단호한 평서문(~이다, ~에 불과하다, ~라는 지적이다)으로 끝내십시오.
        4. **분량**: 공백 포함 800~1000자 내외로, 실제 매체에 기고될 수준의 완성도를 갖추십시오.

        [응답 예시 - 이 정도의 독설과 통찰이 필요합니다]
        {{
          "article_body": "언론의 직무유기가 도를 넘었다. 최근 발생한 XX 사안을 두고 대다수 기성 매체들이 보여준 행태는 '감시자'가 아닌 '확성기'에 가까웠다. 조선일보가 '절차적 정당성'이라는 해괴한 논리로 본질을 세탁할 때, 한국일보 역시 이에 동조하며 주권자의 눈을 가렸다. 팩트 뒤에 숨은 매체의 비겁한 프레임 전쟁 속에서 진실은 파편화되었고, 남은 것은 진영 논리의 배설뿐이다. 언론이 스스로 권력의 앵무새를 자처하는 한, 우리 사회의 공론장은 회복 불가능한 비극으로 치달을 수밖에 없다."
        }}
        """

        try:
            # LLM 호출 - 오직 본문 작성에만 집중 (제목은 기존 Cluster Agent 데이터 사용)
            response_schema = {
                "type": "OBJECT",
                "properties": {
                    "article_body": {"type": "STRING"}
                },
                "required": ["article_body"]
            }
            
            result, usage = call_llm(prompt, "local", state, schema=response_schema)
            
            # 2. 결과 추출 및 코드 레벨 데이터 조립
            llm_body = result.get("article_body") if isinstance(result, dict) else (str(result) if result else "본문 생성 실패")

            final_data = {
                "issue_id": issue_id,
                "title": title,
                "description": description,
                "background": background,
                "core_contentions": state.get("core_contentions", ""),
                "conflict_summary": conflict_summary,
                "media_views": media_views,
                "article_body": llm_body
            }

            total_tokens = update_total_tokens(state, usage, "WriterAgent")
            msg = "비평 기사 본문 작성 및 데이터 조립 완료"
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
            msg = f"본문 생성 실패: {e}"
            logger.error(msg)
            return {"draft_article": {"article_body": msg}, "messages": [msg]}
