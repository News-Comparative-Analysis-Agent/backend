import json
from app.agents.state import ComparisonState
from app.agents.utils import call_llm, update_total_tokens
from app.core.logger import logger, log_llm_event
from langsmith import traceable
from app.domains.issues.repository import IssueRepository

class IssueAgent:
    """
    Agent 2) Issue Agent (쟁점 구조화)
    주장 카드들을 분석하여 서로 충돌하거나 보완하는 '핵심 쟁점(Points of Contention)' 구조를 생성합니다.
    """
    def __init__(self, db=None):
        self.db = db
        self.issue_repo = IssueRepository(db) if db is not None else None

    @traceable(name="Agent 2: Issue (쟁점 구조화) 🧩")
    def node_structure_issues(self, state: ComparisonState) -> dict:
        """
        [Node] Evidence가 만든 media 근거(claim/evidence/url) 위에서,
        LLM이 반드시 "서술형 값" 두 가지(`conflict_summary`, `narrative`)만 생성하도록 제한합니다.

        - 절대 press/claim/evidence/url 같은 factual 필드를 출력값에서 훼손하지 않도록,
          해당 필드는 "입력"으로만 사용하고 출력에는 포함하지 않습니다.
        """
        llm_mode = state.get("llm_mode", "local_priority")
        issue_id = state.get("issue_id")

        # 최상단 메타는 DB에서 가져옵니다. (Evidence/Issue 단계에서 LLM 생성 금지)
        issue_title = ""
        issue_description = ""
        issue_background = ""
        issue_core_contentions = ""
        if self.issue_repo is not None and issue_id is not None:
            issue = self.issue_repo.get_by_id(issue_id)
            if issue is not None:
                issue_title = issue.name or ""
                issue_description = issue.description or ""
                issue_background = issue.background or ""
                issue_core_contentions = issue.core_contentions or ""

        issue_payload_items = state.get("issue_payload_items", []) or []

        # Flatten + press/url 기준 dedupe (narrative 매핑 키)
        media_items: list[dict] = []
        seen = set()
        for item in issue_payload_items:
            for mv in item.get("media_views", []) or []:
                if not isinstance(mv, dict):
                    continue
                press = mv.get("press", "")
                url = mv.get("url", "")
                key = (press, url)
                if key in seen:
                    continue
                seen.add(key)
                media_items.append({
                    "press": press,
                    "claim": mv.get("claim", ""),
                    "evidence": mv.get("evidence", ""),
                    "url": url,
                })

        log_llm_event("agent_issue", f"Agent 2 (Issue): {len(media_items)}개 media 기반 서술 생성 시작")

        if not media_items:
            return {
                "issue_id": issue_id,
                "title": issue_title,
                "description": issue_description,
                "background": issue_background,
                "core_contentions": issue_core_contentions,
                "conflict_summary": "",
                "media_narratives": [],
                "media_views": [],
                "issue_payload_items": [],
                "messages": ["입력 media가 없어 Issue 중단"],
            }

        media_json = json.dumps(media_items, ensure_ascii=False, indent=2)

        prompt = f"""
            당신은 편집국 분석가입니다.
            아래 `media_items`는 Evidence가 추출한 사실 기반 데이터입니다.

            요청:
            1) `conflict_summary`를 하나의 문자열로 생성: 언론사들이 동일 이슈에 대해 서로 다르게 주장하는 핵심 시각 차이 요약.
            2) `media_narratives`를 배열로 생성: 각 항목은 {{press, url, narrative}} 형태이며, narrative는 반드시 해당 media의 claim/evidence에 근거해서 1~2문장으로 서술.

            중요 제한(할루시네이션 방지):
            - press/claim/evidence/url 같은 factual 필드는 출력에서 절대 바꾸지 마세요. (출력에는 narrative만 생성)
            - narrative에는 claim/evidence에 없는 사실/새 인물/새 통계/새 사건을 추가하지 마세요.

            입력: media_items
            {media_json}

            아래 JSON만 출력하세요.
            {{
            "conflict_summary": "언론사 간 시각 차이 요약",
            "media_narratives": [
                {{
                "press": "언론사명",
                "url": "기사 URL",
                "narrative": "서술형 분석 문장"
                }}
            ]
            }}
        """
        
        try:
            usage = {"prompt_tokens": 0, "completion_tokens": 0}
            if llm_mode == "gemini_only":
                import google.generativeai as genai
                response_schema = {
                    "type": "OBJECT",
                    "properties": {
                        "conflict_summary": {"type": "STRING"},
                        "media_narratives": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "press": {"type": "STRING"},
                                    "url": {"type": "STRING"},
                                    "narrative": {"type": "STRING"},
                                },
                                "required": ["press", "url", "narrative"],
                            },
                        },
                    },
                    "required": ["conflict_summary", "media_narratives"],
                }
                gen_model = genai.GenerativeModel(
                    "gemini-2.0-flash",
                    generation_config={"response_mime_type": "application/json", "response_schema": response_schema},
                )
                response = gen_model.generate_content(prompt)
                result = json.loads(response.text)
                # token 추정(정확 토큰 메타는 Gemini SDK가 반환하는 형식이 다를 수 있어 기존 방식처럼 근사 유지)
                usage["prompt_tokens"] = len(prompt) // 4
                usage["completion_tokens"] = len(response.text) // 4
            else:
                result, usage = call_llm(prompt, "7B", state)
            
            # 토큰 업데이트
            total_tokens = update_total_tokens(state, usage, "IssueAgent")

            if not isinstance(result, dict):
                result = {"conflict_summary": "", "media_narratives": []}

            conflict_summary = result.get("conflict_summary", "") or ""
            media_narratives = result.get("media_narratives", []) or []
            if not isinstance(media_narratives, list):
                media_narratives = []

            msg = "conflict_summary 및 media_narratives 서술 생성 완료"
            # 상세 내용(요약 및 매체별 서술)을 로그에 포함
            details = {
                "conflict_summary": conflict_summary,
                "media_narratives": media_narratives
            }
            log_llm_event("agent_issue", msg, details=json.dumps(details, ensure_ascii=False, indent=2))

            # 서버측 조립: factual(claim/evidence/url)은 input(media_items) 그대로 쓰고,
            # narrative는 LLM 출력(media_narratives)에서 press/url 매칭으로만 채웁니다.
            narrative_by_key: dict[tuple[str, str], str] = {}
            for mn in media_narratives:
                if not isinstance(mn, dict):
                    continue
                k = (mn.get("press", "") or "", mn.get("url", "") or "")
                narrative_by_key[k] = mn.get("narrative", "") or ""

            media_views: list[dict] = []
            seen = set()
            for mi in media_items:
                if not isinstance(mi, dict):
                    continue
                press = mi.get("press", "") or ""
                url = mi.get("url", "") or ""
                k = (press, url)
                if k in seen:
                    continue
                seen.add(k)
                media_views.append(
                    {
                        "press": press,
                        "claim": mi.get("claim", "") or "",
                        "evidence": mi.get("evidence", "") or "",
                        "url": url,
                        "narrative": narrative_by_key.get(k, ""),
                    }
                )

            return {
                "issue_id": issue_id,
                "title": issue_title,
                "description": issue_description,
                "background": issue_background,
                "core_contentions": issue_core_contentions,
                "conflict_summary": conflict_summary,
                "media_views": media_views,
                "issue_payload_items": [],
                "messages": [msg],
                "total_tokens": total_tokens,
            }
            
        except Exception as e:
            msg = f"쟁점 구조화 시스템 에러: {e}"
            logger.error(msg)
            log_llm_event("agent_issue", msg)
            return {
                "issue_id": issue_id,
                "title": issue_title,
                "description": issue_description,
                "background": issue_background,
                "core_contentions": issue_core_contentions,
                "conflict_summary": "",
                "media_views": [],
                "issue_payload_items": [],
                "messages": [msg],
            }
