import json
from datetime import datetime
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

    @staticmethod
    def _format_date(published_at: str) -> str:
        """'2026-03-31' → '3월 31일'"""
        try:
            dt = datetime.strptime(published_at, "%Y-%m-%d")
            return f"{dt.month}월 {dt.day}일"
        except Exception:
            return published_at

    @traceable(name="Agent 3: Writer (비평 기사 본문 작성) ✍️")
    def node_write_draft(self, state: ComparisonState) -> dict:
        """
        [Node] 구조화된 쟁점과 근거 데이터를 바탕으로 최종 비평 기사 본문을 작성합니다.
        LLM은 본문 작성에만 집중하며, 나머지 데이터는 코드 레벨에서 조립합니다.
        """
        # 0. 이전 검수 결과가 있다면 피드백 반영
        judge_status   = state.get("judge_status", "")
        judge_feedback = state.get("judge_feedback", "")
        retry_count    = state.get("retry_count", 0)

        feedback_prompt = ""
        if judge_status != "PASS" and judge_feedback:
            feedback_prompt = (
                f"\n\n[데스크 검수 피드백 - 반드시 반영하십시오]\n{judge_feedback}\n"
                "위의 지시사항을 최우선으로 반영하여 기사를 전면 수정하십시오."
            )

        issue_id         = state.get("issue_id")
        title            = state.get("title", "")
        description      = state.get("description", "")
        background       = state.get("background", "")
        conflict_summary = state.get("conflict_summary", "")
        media_views      = state.get("media_views", [])

        log_llm_event("agent_writer", f"Agent 3 (Writer): 비평 기사 본문 작성 시작 (Retry: {retry_count})")

        if not title and not media_views:
            return {"draft_article": {"article_body": "입력 데이터가 부족합니다."}, "messages": ["데이터 부재로 Writer 중단"]}

        # 언론사별 블록 포매팅 — 날짜를 Python에서 직접 가공하여 전달
        media_blocks = ""
        for i, mv in enumerate(media_views, 1):
            date_str       = self._format_date(mv.get("published_at", ""))
            article_title  = mv.get("title", "")   # evidence_agent가 채워주는 필드
            media_blocks += f"""
        --- [{i}번 언론사: {mv.get('press', '알수없음')}] ---
        핵심주장(claim): {mv.get('claim', '')}
        원문 근거(evidence): {mv.get('evidence', '')}
        발행일: {date_str}
        기사제목: {article_title}
        """ 

        prompt = f"""
        당신은 미디어 비평지 '미디어스'의 기자입니다.
        여러 언론사가 동일한 사건을 어떻게 다르게 보도했는지 비교·분석하는 '언론 보도 비평 기사'를 작성하십시오.
        {feedback_prompt}

        [이슈 정보]
        제목: {title}
        배경: {background}
        갈등 요약: {conflict_summary}

        [언론사별 분석 데이터]
        {media_blocks}

        [미디어스 기사 작성 규칙 - 반드시 따를 것]

        1. **기자 의견을 직접 쓰지 마라.**
           - "A언론이 틀렸다", "B언론이 옳다"는 식의 기자 판단은 쓰지 않는다.
           - 각 언론사가 스스로 한 말이 독자에게 판단 근거가 되도록 구성한다.

        2. **각 언론사 소개는 반드시 아래 형식을 따라라.**
           형식: "{{매체명}}는 {{발행일}} 사설 <{{기사제목}}>에서 '...'라고 했다."
           예시: "조선일보는 3월 31일 사설 <잇단 '불법 대북송금' 녹취록 공방, 전문 공개해야>에서 '정치적 이유가 있는 것 아니냐는 의구심이 생길 수 있다'고 했다."
           → {{발행일}}과 {{기사제목}}은 반드시 [언론사별 분석 데이터]의 `발행일`과 `기사제목` 값을 그대로 사용한다.
           → 임의로 생략하거나 다른 표현으로 바꾸지 마라.
           → 기사 제목은 반드시 <>로 감싼다.

        3. **원문 문장을 단 한 글자도 바꾸지 마라.**
           - [언론사별 분석 데이터]의 `원문 근거(evidence)` 문장만 인용한다.
           - 요약하거나 표현을 바꾸는 것은 금지한다.
           - evidence에 없는 문장을 새로 만들거나 추가하는 것은 금지한다.

        4. **대립하는 시각은 '반면'으로 전환하라.**
           - 한쪽 시각의 언론사들을 소개한 뒤 반대 시각으로 넘어갈 때 반드시 "반면"으로 문단을 시작한다.

        5. **같은 언론사의 추가 주장은 '이어'로만 연결하라.**
           - 같은 언론사의 두 번째 인용: "[언론사]는 이어 '...'라고 했다."
           - "또한", "아울러" 등 다른 연결어는 절대 사용하지 않는다.

        [기사 구조 - 아래 순서를 반드시 따를 것]

        (1) 리드 (2문장):
            - 첫 문장: [이슈 정보]의 `배경`을 바탕으로 사건을 한 문장으로 요약한다.
              → 반드시 행위 주체(누가 무엇을 했는지)를 명시한다.
              → 형식: "[주체]가/이 [행위]해 파문이 일고 있다."
            - 두 번째 문장: [이슈 정보]의 `갈등 요약`을 **단 한 글자도 수정하지 않고** 그대로 사용한다.

        (2) 사건 경위 (3~5문장):
            - 언제, 누가, 무엇을 했는지 팩트 중심으로 서술한다.
            - 핵심 발언은 반드시 큰따옴표("")로 직접 인용한다.
            - 각 측의 반박 입장도 포함한다.
            - 여기서 사용한 문장은 (3)번 언론사별 입장 문단에서 재인용하지 않는다.

        (3) 언론사별 입장 (각 언론사마다 2~3문장):
            - 반드시 "[언론사]는 {{발행일}} 사설 <{{기사제목}}>에서..." 형식으로 시작한다.
            - 해당 언론사의 `원문 근거(evidence)` 중 (2)번 사건 경위에서 사용하지 않은 문장을 작은따옴표('')로 인용한다.
            - 같은 논조의 다음 언론사는 자연스럽게 이어 쓴다.
            - 대립 논조의 언론사로 넘어갈 때 반드시 "반면"으로 문단을 시작한다.

        (4) 마무리 없음:
            - 마지막 언론사 인용 문장으로 기사를 끝낸다.
            - 별도의 마무리·요약·정리 문단을 쓰지 않는다.

        [절대 금지 사항]
        - "이처럼", "결국", "이는 ~을 의미한다", "~을 보여준다" 등 기자 해석·논평 문장 금지
        - evidence에 없는 사실 추가 또는 문장 생성 금지
        - 언론사 원문 문장 요약 또는 변형 금지
        - 마무리·결론 문단 작성 금지
        - "또한", "아울러" 등 연결어 사용 금지 (반드시 "이어"만 사용)
        """

        try:
            response_schema = {
                "type": "OBJECT",
                "properties": {
                    "article_body": {"type": "STRING"}
                },
                "required": ["article_body"]
            }

            result, usage = call_llm(prompt, "local", state, schema=response_schema)

            llm_body = result.get("article_body") if isinstance(result, dict) else (str(result) if result else "본문 생성 실패")

            final_data = {
                "issue_id":         issue_id,
                "title":            title,
                "description":      description,
                "background":       background,
                "conflict_summary": conflict_summary,
                "media_views":      media_views,
                "article_body":     llm_body,
            }

            total_tokens = update_total_tokens(state, usage, "WriterAgent")
            msg = "비평 기사 본문 작성 및 데이터 조립 완료"
            log_llm_event("agent_writer", msg, details=json.dumps(final_data, ensure_ascii=False, indent=2))

            return {
                "draft_article":    final_data,
                "title":            final_data["title"],
                "description":      final_data["description"],
                "background":       final_data["background"],
                "conflict_summary": final_data["conflict_summary"],
                "media_views":      final_data["media_views"],
                "messages":         [msg],
                "total_tokens":     total_tokens,
            }

        except Exception as e:
            msg = f"본문 생성 실패: {e}"
            logger.error(msg)
            return {"draft_article": {"article_body": msg}, "messages": [msg]}
