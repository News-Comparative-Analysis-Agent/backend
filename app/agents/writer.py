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
        # 0. 이전 검수 결과가 있다면 피드백 반영
        judge_status = state.get("judge_status", "")
        judge_feedback = state.get("judge_feedback", "")
        retry_count = state.get("retry_count", 0)
        
        feedback_prompt = ""
        if judge_status != "PASS" and judge_feedback:
            feedback_prompt = f"\n\n[데스크 검수 피드백 - 반드시 반영하십시오]\n{judge_feedback}\n위의 지시사항을 최우선으로 반영하여 기사를 전면 수정하십시오."

        issue_id = state.get("issue_id")
        title = state.get("title", "")
        description = state.get("description", "")
        background = state.get("background", "")
        conflict_summary = state.get("conflict_summary", "")
        media_views = state.get("media_views", [])
        
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
        {feedback_prompt}

        [분석 데이터]
        {context_json}

        [작성 지침 - 미디어스 스타일 가이드]
        1. **중립의 함정 탈출**: "엇갈린 반응", "관심이 필요하다"와 같은 기계적 중립 표현을 철저히 배제하십시오. 대신 "본질 흐리기", "프레임 덧씌우기", "받아쓰기 관행" 등 언론의 직무유기를 꾸짖는 용어를 사용하십시오.
        2. **분석 데이터의 유기적 활용**: `media_views`, `background`, `core_contentions`, `conflict_summary`를 기사 전반에 입체적으로 녹여내십시오.
           - **`background`**: 기사 서두에서 사안이 발생하게 된 맥락과 사회적 배경을 설명하여 독자의 이해를 돕고, 비평의 정당성을 확보하십시오.
           - **`core_contentions`**: 본론에서 언론사들이 부딪히고 있는 '진짜 문제'가 무엇인지 명확히 짚어주십시오.
           - **`conflict_summary`**: 편집국장이 정의한 '사건의 전선'입니다. 기사 전반의 기조로 삼아 언론사들의 행태를 비판하십시오.
           - **`published_at` & `press`**: "x월 x일자 [언론사명] 보도"와 같이 기사의 선후관계를 명시하십시오.
           - **`claim` & `evidence`**: 언론사가 내세우는 표면적 주장(`claim`)과 그들이 근거로 제시한 실제 문구(`evidence`)를 인용하십시오.
           - **`thought` & `narrative`**: 기사 이면에 숨겨진 편집자의 의도(`thought`)와 사건을 정의하는 언론사 특유의 관점(`narrative`)을 폭로하십시오.
        3. **논리의 전개**: 
           - **서론**: `background`와 `description`을 토대로 이슈의 본질과 이를 다루는 보수/진보 매체의 기만적인 초기 대응 방식을 지적하며 시작하십시오.
           - **본론**: `core_contentions`에 명시된 핵심 쟁점별로 매체들이 어떻게 논리를 왜곡하거나 특정 사실을 은폐하고 있는지, 추출된 `evidence`를 인용하며 송곳처럼 파고드십시오.
           - **결론**: 언론이 스스로 권력의 확성기를 자처하며 쟁점의 본질을 흐릴 때 발생하는 민주주의의 위기를 경고하며 끝맺으십시오.
        4. 모든 문장은 단호한 평서문(~이다, ~에 불과하다, ~라는 지적이다)으로 끝내십시오.
        5. **분량**: 공백 포함 800~1000자 내외로, 실제 매체에 기고될 수준의 완성도를 갖추십시오.

        [응답 예시 - 이 정도의 독설과 통찰이 필요합니다]
        {{
          "article_body": "언론의 직무유기가 도를 넘었다. 지난 3월 25일 보도된 조선일보의 기사는 '절차적 정당성'이라는 해괴한 논리로 본질을 세탁하는 전형적인 행태를 보였다. 이어 3월 26일 중앙일보 역시 이를 받아쓰며 주권자의 눈을 가렸다. 팩트 뒤에 숨은 매체의 비겁한 프레임 전쟁 속에서 진실은 파편화되었고, 남은 것은 진영 논리의 배설뿐이다. 언론이 스스로 권력의 앵무새를 자처하는 한, 우리 사회의 공론장은 회복 불가능한 비극으로 치달을 수밖에 없다."
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
