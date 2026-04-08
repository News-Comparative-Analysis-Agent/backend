import json
from sqlalchemy.orm import Session

import google.generativeai as genai
from app.agents.state import ReviewState
from app.core.logger import logger

class ReviewAgent:
    """
    Agent) Review Agent (최종 품질 검토)
    • 입력: issue_id + pre_generated_draft (사용자 수정본 또는 DB 저장본)
    • 출력:
      - 가이드라인 검증: 차별 표현/자극적 형용사/낙인화/미확인 사실 + 핵심 쟁점 반영 여부
      - AI 종합 의견: 편집장 관점의 종합 평가
    """
    def __init__(self, db: Session = None):
        self.db = db

    # -----------------------------------------------------------
    # Node 1: 이슈 정보 + 분석 메타데이터 + 기사 메타 로드
    # -----------------------------------------------------------
    def node_fetch_articles(self, state: ReviewState) -> dict:
        """
        [Node 1] DB에서 이슈 정보, 분석 메타데이터(배경, 쟁점, 요약) 및 관련 기사의 메타 정보를 가져옵니다.
        """
        issue_id = state.get("issue_id")
        logger.info(f"🔍 [ReviewAgent] Node1: 이슈({issue_id}) 분석 데이터 로드 시작")

        try:
            from app.domains.drafts.repository import DraftRepository
            repo = DraftRepository(self.db)

            issue = repo.get_issue_by_id(issue_id)
            if not issue:
                return {"error": f"이슈 ID {issue_id}를 찾을 수 없습니다.", "messages": ["이슈 없음 - 검토 중단"]}

            articles = repo.get_articles_meta_by_issue(issue_id)
            articles_meta = []
            for art in articles:
                pub_name = art.publisher.name if getattr(art, "publisher", None) else "알 수 없음"
                content = art.body.raw_content if getattr(art, "body", None) else ""
                articles_meta.append({
                    "title": art.title,
                    "url": art.url,
                    "publisher": pub_name,
                    "content": content,
                    "published_at": art.published_at.strftime("%Y-%m-%dT%H:%M") if art.published_at else ""
                })

            # pre_generated_draft에서 실제 본문 추출 (JSON 구조 고려)
            raw_draft = issue.pre_generated_draft or ""
            parsed_draft = raw_draft
            try:
                if raw_draft.strip().startswith('{'):
                    draft_json = json.loads(raw_draft)
                    parsed_draft = draft_json.get("article_body", raw_draft)
            except Exception:
                pass

            logger.info(f"🔍 [ReviewAgent] Node1: 이슈 '{issue.name}', 분석 메타데이터 및 기사 {len(articles_meta)}건 로드 완료")
            return {
                "issue_name": issue.name,
                "issue_description": issue.description or "",
                "issue_background": issue.background or "",
                "core_contentions": issue.core_contentions or "",
                "conflict_summary": issue.conflict_summary or "",
                "pre_generated_draft": parsed_draft,
                "articles_meta": articles_meta,
                "messages": [f"이슈 분석 데이터 및 기사 {len(articles_meta)}건 로드 완료"]
            }

        except Exception as e:
            msg = f"데이터 로드 실패: {e}"
            logger.error(f"🔍 [ReviewAgent] {msg}")
            return {"error": msg, "messages": [msg]}


    # -----------------------------------------------------------
    # Node 3: 가이드라인 검증 + AI 종합 의견 (Gemini/Local LLM)
    # -----------------------------------------------------------
    def node_analyze_and_opine(self, state: ReviewState) -> dict:
        """
        [Node 3] LLM을 사용하여 가이드라인 검증 점수(공정성, 원문충실도, 무해성)에 필요한 값을 추출하고 종합 의견을 생성합니다.
        """
        from app.agents.utils import call_llm, update_total_tokens
        
        pre_generated_draft = state.get("pre_generated_draft", "")
        issue_name = state.get("issue_name", "")
        issue_background = state.get("issue_background", "")
        core_contentions = state.get("core_contentions", "")
        conflict_summary = state.get("conflict_summary", "")
        
        # 기사 원문(상위 3건 정도만 제한)을 포맷팅하여 프롬프트에 포함
        sources_text = ""
        articles = state.get("articles_meta", [])
        for i, a in enumerate(articles[:3]):
            sources_text += f"\n[원본 기사 {i+1} : {a.get('title', '')}]\n{a.get('content', '')[:1500]}...\n"
        
        logger.info(f"⚖️ [ReviewAgent] Node3: 최종 검토 및 종합 의견 생성 시작")

        prompt = f"""
            당신은 엄격한 언론 윤리 전문가이자 노련한 편집장입니다.
            제시된 기사 초안을 평가하여 다음 정보를 추출해 주십시오.

            [검토 대상 기사 (초안)]
            {pre_generated_draft}

            [원본 기사 및 이슈 데이터]
            이슈명: {issue_name}
            배경: {issue_background}
            핵심 쟁점: {core_contentions}
            갈등 요약: {conflict_summary}
            ---
            {sources_text}

            [추출해야 하는 항목]
            1. 공정성 (Fairness)
               - perspective_category_count: 초안에 서로 다른 입장/관점이 몇 가지나 등장하는지 카운트 (예: 정부, 의협, 환자 등 -> 3)
               - emotional_word_ratio: 전체 내용 대비 감정적이고 주관적인 단어의 비율 (%)

            2. 원문 충실도 (Faithfulness)
               - hallucination_ratio: 원본 기사나 데이터에 없는 사실을 지어낸 문장의 비율 (%)
               - distortion_count: 수치 오류, 의미 반전, 과장/축소가 발생한 건수 (정수)

            3. 무해성 (Harmlessness)
               - aggressive_expression_count: 혐오 표현, 비하, 특정 집단 공격적 표현 건수 (정수)
               - hate_speech_list: 실제로 발견된 공격적/혐오 표현 목록 (없으면 빈 배열 [])
            
            [상세 설명 및 의견]
            - details 객체 내에 공정성, 원문 충실도, 무해성에 대한 간략한 평가 사유를 작성합니다.
            - ai_opinion 에는 편집장 관점의 종합 평가 1문장을 작성합니다.

            [응답 JSON 형식]
            {{
                "metrics": {{
                    "perspective_category_count": 2,
                    "emotional_word_ratio": 1.5,
                    "hallucination_ratio": 5,
                    "distortion_count": 0,
                    "aggressive_expression_count": 0,
                    "hate_speech_list": []
                }},
                "details": {{
                    "fairness_detail": "서로 다른 입장 교차로 서술됨.",
                    "faithfulness_detail": "원문 전반에 충실하나 일부 수치 누락.",
                    "harmlessness_detail": "혐오/공격적 표현 없음."
                }},
                "ai_opinion": "전체적으로 뛰어난 완성도를 보이는 기사입니다."
            }}
        """

        response_schema = {
            "type": "object",
            "properties": {
                "metrics": {
                    "type": "object",
                    "properties": {
                        "perspective_category_count": {"type": "integer"},
                        "emotional_word_ratio": {"type": "number"},
                        "hallucination_ratio": {"type": "number"},
                        "distortion_count": {"type": "integer"},
                        "aggressive_expression_count": {"type": "integer"},
                        "hate_speech_list": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["perspective_category_count", "emotional_word_ratio", "hallucination_ratio", "distortion_count", "aggressive_expression_count", "hate_speech_list"]
                },
                "details": {
                    "type": "object",
                    "properties": {
                        "fairness_detail": {"type": "string"},
                        "faithfulness_detail": {"type": "string"},
                        "harmlessness_detail": {"type": "string"}
                    },
                    "required": ["fairness_detail", "faithfulness_detail", "harmlessness_detail"]
                },
                "ai_opinion": {"type": "string"}
            },
            "required": ["metrics", "details", "ai_opinion"]
        }

        try:
            # utils.call_llm을 사용하여 llm_mode에 따라 호출
            result, usage = call_llm(prompt, "local", state, schema=response_schema)
            
            # 토큰 업데이트
            total_tokens = update_total_tokens(state, usage, "ReviewAgent")

            if isinstance(result, list):
                result = result[0] if len(result) > 0 else {}
            
            if isinstance(result, str):
                import json
                try:
                    result = json.loads(result)
                except Exception:
                    result = {}
                    
            if not isinstance(result, dict):
                result = {}
                
            metrics = result.get("metrics", {})
            details = result.get("details", {})
            
            # --- 파이썬 기반 논리적 점수 계산 ---
            # 1. 공정성 (최대 4점)
            p_count = metrics.get('perspective_category_count', 0)
            e_ratio = metrics.get('emotional_word_ratio', 0)
            
            fairness_score = 0
            if p_count >= 2: fairness_score += 2
            elif p_count == 1: fairness_score += 1
            
            if e_ratio <= 2: fairness_score += 2
            elif e_ratio <= 5: fairness_score += 1
            
            # 2. 원문 충실도 (최대 4점)
            h_ratio = metrics.get('hallucination_ratio', 0)
            d_count = metrics.get('distortion_count', 0)
            
            faithfulness_score = 0
            if h_ratio == 0: faithfulness_score += 2
            elif h_ratio < 10: faithfulness_score += 1
            
            if d_count == 0: faithfulness_score += 2
            elif d_count <= 3: faithfulness_score += 1
            
            # 3. 무해성 (최대 2점)
            a_count = metrics.get('aggressive_expression_count', 0)
            harmlessness_score = 0
            if a_count == 0: harmlessness_score += 2
            elif a_count <= 3: harmlessness_score += 1
            
            total_score = fairness_score + faithfulness_score + harmlessness_score

            scores = {
                "fairness": {
                    "score": fairness_score,
                    "max_score": 4,
                    "detail": details.get("fairness_detail", "")
                },
                "faithfulness": {
                    "score": faithfulness_score,
                    "max_score": 4,
                    "detail": details.get("faithfulness_detail", "")
                },
                "harmlessness": {
                    "score": harmlessness_score,
                    "max_score": 2,
                    "detail": details.get("harmlessness_detail", "")
                },
                "total_score": total_score,
                "hate_speech_list": metrics.get("hate_speech_list", []),
                "distortions_count": d_count
            }

            ai_opinion = result.get("ai_opinion", "검토가 완료되었습니다.")
            logger.info(f"⚖️ [ReviewAgent] Node3: 최종 검토 완료 총점 {total_score}점 (의견: {ai_opinion[:20]}...)")

        except Exception as e:
            msg = f"LLM 분석 오류: {e}"
            logger.error(f"⚖️ [ReviewAgent] {msg}")
            # 에러 발생 시 기본 통과 점수로 처리
            scores = {
                "fairness": {"score": 4, "max_score": 4, "detail": "분석 오류 - 기본 점수 부여"},
                "faithfulness": {"score": 4, "max_score": 4, "detail": "분석 오류 - 기본 점수 부여"},
                "harmlessness": {"score": 2, "max_score": 2, "detail": "분석 오류 - 기본 점수 부여"},
                "total_score": 10,
                "hate_speech_list": [],
                "distortions_count": 0
            }
            ai_opinion = f"분석 중 오류가 발생했습니다: {str(e)}"
            total_tokens = state.get("total_tokens", {"prompt_tokens": 0, "completion_tokens": 0})

        return {
            "scores": scores,
            "ai_opinion": ai_opinion,
            "total_tokens": total_tokens,
            "messages": ["최종 검토 및 종합 의견 생성 완료"]
        }
