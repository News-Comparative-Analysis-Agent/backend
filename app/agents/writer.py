import json
import google.generativeai as genai
from app.agents.state import ComparisonState
from app.agents.utils import call_local_llm
from app.core.logger import logger, log_llm_event

class WriterAgent:
    """
    Agent 3) Writer Agent (비평 기사 초안 생성)
    • 입력: 쟁점 구조 + 근거
    • 출력: 비평 기사 초안(고정 템플릿)
      o 서론(이슈 소개)
      o 쟁점1~3(매체별 관점 비교)
      o 정리(논점 요약)
    • 필수 규칙: 각 쟁점 문단 끝에 “근거(출처 링크)”를 반드시 포함
    """
    def __init__(self):
        pass

    def node_write_draft(self, state: ComparisonState) -> dict:
        """
        [Node] 구조화된 쟁점과 근거 데이터를 바탕으로 기사 초안을 작성합니다.
        Judge의 피드백이 있다면 이를 반영하여 다시 작성합니다.
        """
        structured_issues = state.get("structured_issues", [])
        judge_feedback = state.get("judge_feedback", "")
        judge_status = state.get("judge_status", "")
        retry_count = state.get("retry_count", 0)
        llm_mode = state.get("llm_mode", "local_priority")
        
        log_llm_event("agent_writer", f"Agent 3 (Writer): 비평 초안 작성 시작 (Retry: {retry_count})")
        
        if not structured_issues:
            return {"draft_article": "구조화된 쟁점 데이터가 없어 작성을 진행할 수 없습니다.", "messages": ["쟁점 부재로 Writer 중단"]}
            
        issues_json = json.dumps(structured_issues, ensure_ascii=False, indent=2)
        
        prompt = f"""
        당신은 수석 논설위원입니다. 다음은 여러 언론사들의 관점 차이를 정리한 '핵심 쟁점(Issue)' 데이터입니다.
        이를 바탕으로 고정된 템플릿에 맞춰 비교 비평 기사의 초안을 작성하세요.
        
        [쟁점 데이터 목록]
        {issues_json}
        
        [고정 템플릿]
        ## 서론
        (이 사건/이슈가 무엇인지, 왜 중요한지 간략히 요약)
        
        ## 쟁점 분석
        ### 쟁점 1: [첫 번째 쟁점 제목]
        (매체별 관점 비교 서술)
        *근거: [A 매체](URL), [B 매체](URL)*
        
        ### 쟁점 2: [두 번째 쟁점 제목]
        (매체별 관점 비교 서술)
        *근거: [C 매체](URL)*
        
        (필요 시 쟁점 3, 4 등 추가)
        
        ## 정리 및 결론
        (향후 전망 및 논점 요약)
        
        [필수 규칙 🚨]
        1. 각 쟁점 문단의 끝에는 반드시 **"*근거: [매체명](URL), ...*"** 형식으로 출처 링크를 명시하십시오. (URL이 없다면 매체명이라도 작성)
        2. 제공된 쟁점 데이터에 없는 새로운 주장을 지어내지 마십시오.
        3. 마크다운 언어만을 사용하여 본문만 바로 출력하십시오.
        """
        
        # 이전 Judge 단계에서 Writer를 향한 반려 사유가 있다면 프롬프트에 추가
        if judge_status == "FAIL_WRITER" and judge_feedback:
            prompt += f"""
            
            [🚨 이전 초안 검토 피드백 반영 필수 🚨]
            편집장(Judge)으로부터 다음과 같은 피드백이 도착했습니다. 
            반드시 이 내용에 맞추어 초안을 전면 수정하십시오.
            
            피드백 내용: {judge_feedback}
            """
            log_llm_event("agent_writer", f"Writer 피드백 반영 모드 활성화: {judge_feedback}")
            
        try:
            if llm_mode == "gemini_only":
                gen_model = genai.GenerativeModel('gemini-2.0-flash')
                response = gen_model.generate_content(prompt)
                final_text = response.text
            else:
                final_text = call_local_llm("7B_2", prompt)
                
            msg = "비평 보고서 초안(Draft) 생성 완료"
            log_llm_event("agent_writer", msg)
            return {"draft_article": final_text, "messages": [msg]}
            
        except Exception as e:
            msg = f"초안 생성 실패: {e}"
            logger.error(msg)
            log_llm_event("agent_writer", msg)
            return {"draft_article": "보고서 생성 중 오류가 발생했습니다.", "messages": [msg]}
