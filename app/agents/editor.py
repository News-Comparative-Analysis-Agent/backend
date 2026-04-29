from app.agents.state import ComparisonState
from app.agents.utils import update_total_tokens, call_llm
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
            content_snippet = art.get("content", "")[:150]
            articles_context += f"--- [원본 {i}: {art.get('press', '알수없음')}] ---\n{content_snippet}...\n\n"

        # ... (중략: prompt 구성 로직은 유지하되 출력 형식 예시만 단순화)
        prompt = f"""
        당신은 사안의 횡단적 분석을 전문으로 하는 신문사의 **수석 논설위원**입니다.
        아래 [비평 기사 초안]을 교정하여, 날카로운 통찰과 유려한 문장이 조화된 **최종 비평 리포트**로 완성하십시오.

        [비평 기사 초안]
        {json.dumps(draft, ensure_ascii=False, indent=2) if isinstance(draft, dict) else draft}

        [참조용 원본 뉴스 (각 150자)]
        {articles_context}

        [에디팅 가이드라인]
        1. **나열 금지**: 언론사를 나열하지 말고 '쟁점' 중심으로 서술을 통합하십시오.
        2. **논리적 연결**: '반면', '결과적으로' 등 연결어를 적극적으로 사용하여 문장을 매끄럽게 이으십시오.
        3. **통찰력 있는 제목**: 사안의 본질을 짚는 압축적인 제목으로 교정하십시오.

        [출력 JSON 형식]
        {{
          "article_body": "교정 및 다듬기가 완료된 최종 비평 본문"
        }}
        """
        
        # LLM 호출
        try:
            response_schema = {
                "type": "OBJECT",
                "properties": {
                    "article_body": {"type": "STRING"}
                },
                "required": ["article_body"]
            }

            result, usage = call_llm(prompt, "local", state, schema=response_schema)
            
            # 데이터 복구 및 조립
            # 제목은 Cluster Agent의 원본 title을 유지 (Writer가 조립한 draft_article["title"] 활용)
            final_title = state.get("title") or (draft.get("title") if isinstance(draft, dict) else "제목 없음")
            final_body = result.get("article_body") if isinstance(result, dict) else (str(result) if result else "본문 생성 실패")

            # 최종 데이터 구조 완성
            edited_article = {
                "issue_id": issue_id_int,
                "title": final_title,
                "description": state.get("description") or (draft.get("description") if isinstance(draft, dict) else "설명 없음"),
                "background": state.get("background") or (draft.get("background") if isinstance(draft, dict) else ""),
                "conflict_summary": state.get("conflict_summary") or (draft.get("conflict_summary") if isinstance(draft, dict) else ""),
                "media_views": state.get("media_views") or (draft.get("media_views") if isinstance(draft, dict) else []),
                "article_body": final_body
            }

            # 토큰 업데이트
            total_tokens = update_total_tokens(state, usage, "EditorAgent")

            # 데이터 보조 로깅 및 종료
            log_llm_event("agent_editor", "비평 기사 교정 완료", details=json.dumps(edited_article, ensure_ascii=False, indent=2))
                
            return {
                "edited_article": edited_article, 
                "messages": ["표현 및 중복 톤 정리 완료"],
                "total_tokens": total_tokens
            }
            
        except Exception as e:
            msg = f"에디팅 실패: {e}"
            logger.error(f"🎨 [EditorAgent] {msg}")
            return {"edited_article": draft, "messages": [msg]}
