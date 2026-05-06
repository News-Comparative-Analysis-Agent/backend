import os
import json
import time
from typing import List, Optional
from difflib import SequenceMatcher

from google import genai
from sqlalchemy.orm import Session
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.domains.drafts.repository import DraftRepository
from app.domains.drafts.schemas import (
    ChatRequest, ChatResponse, ChatAIOutputSchema, ImageItem, 
    SimilarityRequest, SimilarityResponse,
    ArticleInfo, PerspectiveItem, PerspectivesResponse,
    SaveDraftRequest, SaveDraftResponse,
    FinalReviewResponse, WorkspaceDraftSummary,
    GuidelineCheck, ArticleSourceItem,
    CitationItem, DraftWithCitationsResponse
)
from app.core.logger import logger

# Gemini 초기 설정 (신규 SDK 방식)
_draft_genai_client = None

def get_draft_genai_client():
    global _draft_genai_client
    if _draft_genai_client is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if api_key:
            _draft_genai_client = genai.Client(api_key=api_key)
    return _draft_genai_client

def get_gemini_model_name():
    """환경 변수에서 Gemini 모델명을 가져오거나 기본값을 반환합니다."""
    return os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")

# 관점 분석용 매핑 단어 딕셔너리
PUBLISHER_STANCE = {
    "한겨레": "progressive",
    "경향신문": "progressive",
    "조선일보": "conservative",
    "동아일보": "conservative",
    "연합뉴스": "neutral",
}

STANCE_KOREAN = {
    "progressive": "진보",
    "conservative": "보수",
    "neutral": "중립",
    "unknown": "기타"
}

class DraftService:
    """
    기사 작성(Drafts)과 관련된 모든 비즈니스 로직(AI 분석, 스트리밍, 유사도 검사)을 담당합니다.
    """
    def __init__(self, db: Session):
        self.repo = DraftRepository(db)

    # ==========================================
    # 1. 자동 초안 생성 (비평 기사 스트리밍) 로직
    # ==========================================
    async def _stream_generator(self, prompt: str, pre_generated_text: str = None):
        try:
            # 미리 생성된 초안이 있으면 AI를 호출하지 않고 스트리밍 흉내만 내서 즉각 반환
            if pre_generated_text:
                # 텍스트를 약간씩 나눠서 전송하여 스트리밍 효과 (선택 사항)
                chunk_size = 50
                for i in range(0, len(pre_generated_text), chunk_size):
                    chunk = pre_generated_text[i:i+chunk_size]
                    data = json.dumps({"text": chunk}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
                    time.sleep(0.05) # 약간의 딜레이로 스트리밍 느낌
                return

            client = get_draft_genai_client()
            if not client:
                yield f"data: {json.dumps({'text': 'Gemini Client not initialized'}, ensure_ascii=False)}\n\n"
                return

            for chunk in client.models.generate_content(
                model=get_gemini_model_name(),
                contents=prompt,
                config={'stream': True}
            ):
                if chunk.text:
                    text_chunk = chunk.text
                    data = json.dumps({"text": text_chunk}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
        except Exception as e:
            error_msg = json.dumps({"text": f"\n\n[Error] 생성 중 오류 발생: {str(e)}"}, ensure_ascii=False)
            yield f"data: {error_msg}\n\n"


    # ==========================================
    # 2. AI 챗봇 (초안 첨삭) 로직
    # ==========================================
    def chat_with_ai(self, request: ChatRequest) -> ChatResponse:
        client = get_draft_genai_client()
        if not client:
            raise HTTPException(status_code=500, detail="Google Gemini API Key is not configured.")

        try:
            pre_generated_context = ""
            if request.issue_id:
                issue = self.repo.get_issue_by_id(request.issue_id)
                if issue and issue.pre_generated_draft:
                    pre_generated_context = f"\n\n[우리 시스템에서 생성한 관련 이슈 기사 원본 (참고용)]\n{issue.pre_generated_draft}\n"

            system_prompt = """
당신은 기사 작성을 돕는 스마트 AI 어시스턴트입니다.
사용자는 현재 뉴스 기사 초안을 작성하고 있는 기자입니다.

[역할]
1. 모든 응답은 **반드시 한국어로만 작성**해야 합니다. 절대 중국어나 다른 외국어를 사용하지 마세요.
2. 사용자의 질문에 친절하고 전문적으로 답변하세요.
3. 'draft_content'가 제공되면, 문맥을 파악하여 피드백을 제공하세요.
4. 제공된 '[우리 시스템에서 생성한 관련 이슈 기사 원본 (참고용)]'이 있다면, 해당 내용을 바탕으로 더 일관성 있고 맥락에 맞는 답변을 제공하세요.
5. **중요**: 사용자가 초안 수정을 명시적으로 요청하거나 조언을 구하면, 당신은 **반드시 `modified_content` 필드에 처음부터 끝까지 수정 및 완성된 기사 전체 내용(Full Text)을 작성해야 합니다.** 다시 말해, `response` 필드에는 간단한 안내 멘트만 적고 실제 수정본은 모두 `modified_content`에 넣으세요!
"""
            # context_message: 현재 작성 중인 내용과 시스템 컨텍스트
            context_message = f"{pre_generated_context}\n\n[현재 작성 중인 초안 (draft_content)]\n{request.draft_content or '(내용 없음)'}\n\n"
            
            if request.messages:
                # 1. 대화 히스토리 구성 (멀티턴 지원)
                history_list = []
                for m in request.messages[:-1]:
                    role_label = "사용자" if m.role == "user" else "AI"
                    history_list.append(f"[{role_label}]: {m.content}")
                
                history_text = "\n".join(history_list)
                last_user_input = request.messages[-1].content
                
                # 2. 최종 프롬프트 구성
                user_prompt = f"{context_message}"
                if history_text:
                    user_prompt += f"[이전 대화 히스토리]\n{history_text}\n\n"
                user_prompt += f"[사용자 질문]\n{last_user_input}"

                # 3. Gemini API 호출 (System Instruction 분리 및 Schema 적용)
                response = client.models.generate_content(
                    model=get_gemini_model_name(),
                    contents=user_prompt,
                    config={
                        "system_instruction": system_prompt,
                        "response_mime_type": "application/json",
                        "response_schema": ChatAIOutputSchema
                    }
                )
                
                try:
                    # [개선] 명확한 JSON 파싱 및 에러 핸들링
                    if not response.text:
                         return ChatResponse(response="AI가 응답을 생성하지 못했습니다. 다시 시도해주세요.", modified_content=None)
                         
                    result_data = json.loads(response.text)
                    return ChatResponse(
                        response=result_data.get("response", ""),
                        modified_content=result_data.get("modified_content")
                    )
                except json.JSONDecodeError as e:
                    logger.error(f"❌ JSON 파싱 에러: {str(e)} | Response: {response.text}")
                    return ChatResponse(
                        response="AI 응답을 처리하는 중 형식이 맞지 않는 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
                        modified_content=None
                    )
            else:
                return ChatResponse(response="무엇을 도와드릴까요?", modified_content=None)
        except Exception as e:
            logger.error(f"❌ Gemini Chat Error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"AI 응답 생성 중 오류가 발생했습니다: {str(e)}")

    def _normalize_image_url(self, url: str) -> str:
        """
        이미지 URL을 정규화하여 동일 이미지의 중복 노출을 방지합니다.
        (예: Naver News의 ?type=w800, ?type=w860 등을 동일 이미지로 간주)
        """
        if not url:
            return ""
        # 쿼리 파라미터 제거 (단, 일부 사이트에서 쿼리 자체가 이미지 ID인 경우 주의가 필요할 수 있으나 뉴스 사이트 특성상 대부분 해상도임)
        base_url = url.split('?')[0]
        if base_url.startswith('//'):
            base_url = 'https:' + base_url
        return base_url.strip()

    # ==========================================
    # 3. 이미지 추출 로직
    # ==========================================
    async def get_issue_images(self, issue_id: int) -> List[ImageItem]:
        import asyncio
        import aiohttp
        from bs4 import BeautifulSoup

        # 1. 이슈 관련 기사 조회 (중복 제거된 리스트 확보)
        raw_articles = self.repo.get_articles_by_issue_with_publisher(issue_id)
        if not raw_articles:
            return []
            
        # ID 기준 중복 기사 제거 (레포지토리 distinct가 있지만 서비스 단에서도 한번 더 보장)
        articles = []
        seen_article_ids = set()
        for art in raw_articles:
            if art.id not in seen_article_ids:
                articles.append(art)
                seen_article_ids.add(art.id)

        images = []
        seen_normalized_urls = set()

        # 2. DB에 이미 저장된 이미지들을 1차로 로드
        for art in articles:
            if art.image_urls:
                for url in art.image_urls:
                    norm_url = self._normalize_image_url(url)
                    if norm_url and norm_url not in seen_normalized_urls:
                        seen_normalized_urls.add(norm_url)
                        pub_name = art.publisher.name if getattr(art, "publisher", None) else "알 수 없음"
                        images.append(ImageItem(
                            url=url, # 원본 URL 유지 (또는 정규화된 URL 사용 선택 가능)
                            title=art.title,
                            publisher=pub_name,
                            published_at=art.published_at.strftime("%Y-%m-%d") if art.published_at else ""
                        ))
                        
        # 3. 추가 이미지 동적 스크래핑 (최대 10개 기사)
        async def fetch_article_images_dynamically(session, art):
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
                async with session.get(art.url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        # 뉴스 본문 영역 셀렉터들
                        content_area = soup.select_one('#dic_area') or soup.select_one('#newsct_article') or soup.select_one('.go_trans._article_content')
                        
                        if content_area:
                            pub_name = art.publisher.name if getattr(art, "publisher", None) else "알 수 없음"
                            for img in content_area.select('img'):
                                src = img.get('data-src') or img.get('src')
                                if not src: continue
                                
                                norm_src = self._normalize_image_url(src)
                                if norm_src and norm_src not in seen_normalized_urls and not src.startswith('data:'):
                                    seen_normalized_urls.add(norm_src)
                                    images.append(ImageItem(
                                        url=src,
                                        title=art.title,
                                        publisher=pub_name,
                                        published_at=art.published_at.strftime("%Y-%m-%d") if art.published_at else ""
                                    ))
            except Exception as e:
                logger.warning(f"추가 이미지 동적 스크래핑 실패 ({art.url}): {e}")

        # 제한적인 기사 수에 대해서 동시 스크래핑 진행
        async with aiohttp.ClientSession() as session:
            tasks = [fetch_article_images_dynamically(session, art) for art in articles[:10]]
            if tasks:
                await asyncio.gather(*tasks)

        return images


    # ==========================================
    # 6. 작업실 저장 (초안 복사) 로직
    # ==========================================
    def save_issue_draft_to_workspace(self, user_id: int, request: SaveDraftRequest) -> int:
        """
        초안 저장 및 업데이트 (통합 버전)
        - User의 draft_issue_ids에 추가함.
        - 만약 request에 content가 있으면 IssueLabel의 pre_generated_draft를 업데이트함.
        """
        from app.domains.users.models import User
        user = self.repo.db.query(User).get(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        issue = self.repo.get_issue_by_id(request.issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="이슈를 찾을 수 없습니다.")

        # 1. 내용이 있으면 업데이트 (동시 처리)
        if request.content is not None:
            issue.pre_generated_draft = request.content
            
        # 2. 작업실 목록에 추가
        if user.draft_issue_ids is None:
            user.draft_issue_ids = []
            
        if request.issue_id not in user.draft_issue_ids:
            new_list = list(user.draft_issue_ids)
            new_list.append(request.issue_id)
            user.draft_issue_ids = new_list
            self.repo.db.add(user)
            
        self.repo.db.commit()
        return request.issue_id

    def get_user_workspace_drafts(self, user_id: int) -> List[WorkspaceDraftSummary]:
        """
        현재 유저의 작업실에 보관 중인 초안 리스트를 가져옵니다.
        """
        from app.domains.users.models import User
        from app.domains.issues.models import IssueLabel
        import json

        user = self.repo.db.query(User).get(user_id)
        if not user or not user.draft_issue_ids:
            return []

        # 작업 중인 이슈들 조회
        issues = self.repo.db.query(IssueLabel).filter(IssueLabel.id.in_(user.draft_issue_ids)).all()
        
        # ID 순서대로 정렬 (최신 순 등을 원할 경우 created_at 등 사용)
        results = []
        # user.draft_issue_ids 순서(추가된 순서)를 유지하려면 매핑 필요
        issue_map = {issue.id: issue for issue in issues}
        
        from datetime import datetime
        for iid in reversed(user.draft_issue_ids): # 최신 추가 순
            if iid in issue_map:
                issue = issue_map[iid]
                results.append(WorkspaceDraftSummary(
                    issue_id=issue.id,
                    title=issue.name,
                    updated_at=getattr(issue, "created_at", datetime.now())
                ))
        
        return results

    def update_issue_draft(self, issue_id: int, content: str, user_id: int) -> int:
        """
        이슈의 초안 내용을 업데이트합니다 (공유 저장소 방식).
        """
        from app.domains.users.models import User
        
        issue = self.repo.get_issue_by_id(issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="이슈를 찾을 수 없습니다.")
            
        # 1. 초안 내용 업데이트 (공유 저장소)
        issue.pre_generated_draft = content
        
        # 2. 유저의 작업 이력에 추가 (작업실 목록 노출용)
        user = self.repo.db.query(User).get(user_id)
        if user:
            if user.draft_issue_ids is None:
                user.draft_issue_ids = []
            if issue_id not in user.draft_issue_ids:
                new_list = list(user.draft_issue_ids)
                new_list.append(issue_id)
                user.draft_issue_ids = new_list
                self.repo.db.add(user)
        
        self.repo.db.commit()
        return issue_id

    def get_issue_draft_content(self, issue_id: int) -> str:
        """
        특정 이슈의 공유 초안 본문을 가져옵니다.
        """
        issue = self.repo.get_issue_by_id(issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="이슈를 찾을 수 없습니다.")
        return issue.pre_generated_draft or ""

    # ==========================================
    # 7. 최종 품질 검토 로직 (Final Review) - LangGraph 적용
    # ==========================================
    async def run_final_review(self, issue_id: int) -> FinalReviewResponse:
        """
        사용자 수정본을 기반으로 최종 품질 검토 리포트를 생성합니다. (LangGraph Flow)
        """
        from app.scroller.graph import create_review_graph
        from app.scroller.repository import ScrollerRepository

        # 1. 시스템 설정에서 LLM 모드 가져오기
        scroller_repo = ScrollerRepository(self.repo.db)
        settings = scroller_repo.get_system_settings()
        llm_mode = settings.llm_mode if settings else "local_only"

        # 2. 그래프 생성 및 실행
        app = create_review_graph(self.repo.db)
        
        initial_state = {
            "issue_id": issue_id,
            "llm_mode": llm_mode,
            "total_tokens": {"prompt_tokens": 0, "completion_tokens": 0},
            "messages": []
        }

        try:
            # LangGraph 실행
            final_state = await app.ainvoke(initial_state)

            if "error" in final_state and final_state["error"]:
                raise HTTPException(status_code=500, detail=final_state["error"])

            # 3. 결과 리포트 조립
            sources = [
                ArticleSourceItem(
                    title=src["title"],
                    publisher=src["publisher"],
                    url=src["url"],
                    published_at=src["published_at"]
                ) for src in final_state.get("articles_meta", [])
            ]

            # 4. 이슈 기본 정보 조회
            issue = self.repo.get_issue_by_id(issue_id)
            if not issue:
                raise HTTPException(status_code=404, detail="이슈를 찾을 수 없습니다.")

            from app.domains.drafts.schemas import ReviewScores

            return FinalReviewResponse(
                id=issue.id,
                name=issue.name,
                description=issue.description,
                background=issue.background,
                core_contentions=issue.conflict_summary,
                created_at=issue.created_at,
                updated_at=getattr(issue, "updated_at", issue.created_at), # 신규 필드 (없으면 created_at)
                pre_generated_draft=issue.pre_generated_draft,
                sources=sources,
                scores=ReviewScores(**final_state.get("scores", {})),
                ai_opinion=final_state.get("ai_opinion", "의견을 생성할 수 없습니다.")
            )

        except Exception as e:
            logger.error(f"❌ [FinalReview Graph] 실행 중 오류: {e}")
            raise HTTPException(status_code=500, detail=f"품질 검토 중 오류가 발생했습니다: {str(e)}")

    # ==========================================
    # 8. 인용 출처 조회 (Citation Feature)
    # ==========================================
    def get_draft_with_citations(self, issue_id: int) -> DraftWithCitationsResponse:
        """
        DB에 저장된 pre_generated_draft와 ArticleClaim을 바탕으로
        [N] citation 마커가 삽입된 기사 본문과 출처 배열을 반환합니다.
        """
        from app.agents.utils import annotate_citations

        issue = self.repo.get_issue_by_id(issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="이슈를 찾을 수 없습니다.")

        article_body = issue.pre_generated_draft or ""
        if not article_body:
            raise HTTPException(status_code=404, detail="저장된 초안이 없습니다.")

        # ArticleClaim 테이블에서 media_views 형태로 조회
        media_views = self.repo.get_media_views_by_issue(issue_id)

        # citation 마커 실시간 삽입
        annotated_body, raw_citations = annotate_citations(article_body, media_views)

        citations = []
        for c in raw_citations:
            try:
                citations.append(
                    CitationItem(
                        id=c.get("id", 0),
                        press=c.get("press", "알수없음"),
                        title=c.get("title", ""),
                        url=c.get("url", ""),
                        published_at=c.get("published_at", ""),
                        article_id=c.get("article_id"),
                        quote=c.get("quote", ""),
                        evidence=c.get("evidence", "")
                    )
                )
            except Exception as e:
                logger.error(f"❌ [DraftService] CitationItem 변환 실패: {str(e)}")

        logger.info(f"📎 [DraftService] issue_id={issue_id} | 원본 {len(raw_citations)}개 -> 변환 {len(citations)}개")

        return DraftWithCitationsResponse(
            issue_id=issue_id,
            title=issue.name,
            article_body=annotated_body,
            citations=citations
        )

    def get_article_body(self, article_id: int) -> Optional[str]:
        """기사 원문(raw_content)을 반환합니다. lazy-load API에서 사용합니다."""
        return self.repo.get_article_body(article_id)
