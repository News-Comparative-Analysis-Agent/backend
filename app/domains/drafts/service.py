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
    ChatRequest, ChatResponse, ImageItem, 
    SimilarityRequest, SimilarityResponse,
    ArticleInfo, PerspectiveItem, PerspectivesResponse,
    SaveDraftRequest,
    FinalReviewResponse,
    GuidelineCheck, ArticleSourceItem
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
                model='gemini-2.0-flash',
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

    def generate_draft_stream(self, issue_id: int, user_id: Optional[int] = None):
        from app.domains.users.models import User
        context_text = ""
        pre_generated_draft = None
        
        if issue_id:
            issue = self.repo.get_issue_by_id(issue_id)
            if issue:
                # IssueLabel의 pre_generated_draft를 최신 초안으로 사용
                if issue.pre_generated_draft:
                    pre_generated_draft = issue.pre_generated_draft
                
                articles = self.repo.get_articles_by_issue_with_publisher(issue_id, limit=5)
                article_summaries = []
                for idx, art in enumerate(articles, 1):
                    publisher_name = art.publisher.name if getattr(art, "publisher", None) else "알 수 없는 언론사"
                    article_summaries.append(f"[{idx}] 언론사: {publisher_name} | 제목: {art.title}\n요약: {art.summary or '내용 없음'}")
                
                context_text = f"""
                [참고 자료]
                주제: {issue.name}
                
                관련 기사 요약:
                {chr(10).join(article_summaries)}
                """
        
        system_prompt = f"""
# Role (당신의 역할)
당신은 대한민국 언론의 보도 행태를 날카롭게 분석하는 **'미디어 전문 비평가'**입니다.
주어진 5개 내외의 뉴스 기사들을 읽고, 해당 이슈를 바라보는 **언론사별 시각 차이(Frame)**를 비교 분석하는 기사를 작성하세요.

# Input Data (분석할 기사 목록)
{context_text} 

# Analysis Goals (분석 목표)
1. **쟁점 파악**: 이 사안의 핵심 팩트(Fact)는 무엇인가?
2. **구도 설정**: 언론사들의 반응이 어떻게 갈리는가?
3. **논조 비교**: 각 언론사가 주장을 뒷받침하기 위해 어떤 근거를 들었는가?

# Writing Guidelines (작성 지침)
기사는 아래 **5단 구성**을 엄격히 지켜 작성해 주세요.
1. **[헤드라인]**: 이슈의 핵심과 언론의 대립 구도가 한눈에 보이는 제목
2. **[전문 (Lead)]**: 사건의 개요 요약
3. **[본문 1 - 팩트]**: 주관적 해석 배제, 사건 자체의 Fact 서술
4. **[본문 2 - 시각 A (제1그룹)]**: 언론사 실명 언급, 핵심 논리 인용
5. **[본문 3 - 시각 B (제2그룹)]**: 반대편 언론사 서술
6. **[결론 (Closing)]**: 프레임 해석 멘트로 마무리

# Tone & Manner
- 단편적인 사실뿐만 아니라 제3자의 관찰자 시점 유지
- 마크다운 등 코드블록 금지
        """
        return StreamingResponse(
            self._stream_generator(prompt=system_prompt, pre_generated_text=pre_generated_draft), 
            media_type="text/event-stream"
        )

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
사용자는 현재 뉴스 기사 초안을 작성하고 있는 기자 또는 작가입니다.

[역할]
1. 사용자의 질문에 친절하고 전문적으로 답변하세요.
2. 'draft_content'가 제공되면, 문맥을 파악하여 피드백을 제공하세요.
3. 제공된 '[우리 시스템에서 생성한 관련 이슈 기사 원본 (참고용)]'이 있다면, 해당 내용을 바탕으로 더 일관성 있고 맥락에 맞는 답변을 제공하세요.
4. **중요**: 사용자가 초안 수정을 명시적으로 요청하거나 조언을 구하면, 당신은 **반드시 `modified_content` 필드에 처음부터 끝까지 수정 및 완성된 기사 전체 내용(Full Text)을 작성해야 합니다.** 다시 말해, `response` 필드에는 간단한 안내 멘트만 적고 실제 수정본은 모두 `modified_content`에 넣으세요!

[출력 형식]
반드시 다음 JSON 형식으로만 응답하세요. 마크다운 코드 블록(` ```json `)을 포함하지 마세요.
{
    "response": "수정 방향이나 안내 멘트 등 사용자에게 할 말 (한국어)",
    "modified_content": "수정된 전체 기사 초안 텍스트 (수정 요청일 경우 필수 작성, 질문만 있으면 null)"
}
            """
            context_message = f"{system_prompt}{pre_generated_context}\n\n[현재 작성 중인 초안 (draft_content)]\n{request.draft_content}\n\n"
            
            if request.messages:
                last_user_input = request.messages[-1].content
                full_prompt = context_message + f"[사용자 질문]\n{last_user_input}"
                
                response = client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=full_prompt,
                    config={"response_mime_type": "application/json"}
                )
                
                try:
                    result = json.loads(response.text)
                    return ChatResponse(
                        response=result.get("response", ""),
                        modified_content=result.get("modified_content")
                    )
                except json.JSONDecodeError:
                    return ChatResponse(response=response.text, modified_content=None)
            else:
                return ChatResponse(response="무엇을 도와드릴까요?", modified_content=None)
        except Exception as e:
            logger.error(f"❌ Gemini Chat Error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"AI 응답 생성 중 오류가 발생했습니다: {str(e)}")

    # ==========================================
    # 3. 이미지 추출 로직
    # ==========================================
    async def get_issue_images(self, issue_id: int) -> List[ImageItem]:
        import asyncio
        import aiohttp
        from bs4 import BeautifulSoup

        articles = self.repo.get_articles_by_issue_with_publisher(issue_id)
        if not articles:
            return []

        images = []
        seen_urls = set()

        # 1. DB에 이미 저장된 이미지들을 1차로 로드
        for art in articles:
            if art.image_urls:
                for url in art.image_urls:
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        pub_name = art.publisher.name if getattr(art, "publisher", None) else "알 수 없음"
                        images.append(ImageItem(
                            url=url,
                            title=art.title,
                            publisher=pub_name,
                            published_at=art.published_at.strftime("%Y-%m-%d") if art.published_at else ""
                        ))
                        
        # 2. 충분한 이미지가 없거나 과거 데이터 보정 위해, 비동기 온더플라이 스크래핑 시도
        async def fetch_article_images_dynamically(session, art):
            try:
                headers = {"User-Agent": "Mozilla/5.0"}
                async with session.get(art.url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        content_area = soup.select_one('#dic_area') or soup.select_one('#newsct_article') or soup.select_one('.go_trans._article_content')
                        
                        if content_area:
                            pub_name = art.publisher.name if getattr(art, "publisher", None) else "알 수 없음"
                            for img in content_area.select('img'):
                                src = img.get('data-src') or img.get('src')
                                if src and src not in seen_urls and not src.startswith('data:'):
                                    seen_urls.add(src)
                                    images.append(ImageItem(
                                        url=src,
                                        title=art.title,
                                        publisher=pub_name,
                                        published_at=art.published_at.strftime("%Y-%m-%d") if art.published_at else ""
                                    ))
            except Exception as e:
                logger.warning(f"추가 이미지 동적 스크래핑 실패 ({art.url}): {e}")

        # 제한적인 기사 수에 대해서 동시 스크래핑 진행 (모든 기사는 너무 오래 걸리므로 limit 10)
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
        llm_mode = settings.llm_mode if settings else "gemini_only"

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
                ArticleSourceItem(**src) for src in final_state.get("articles_meta", [])
            ]

            guideline_checks = [
                GuidelineCheck(**check) for check in final_state.get("guideline_checks", [])
            ]

            # 4. 이슈 기본 정보 조회
            issue = self.repo.get_issue_by_id(issue_id)
            if not issue:
                raise HTTPException(status_code=404, detail="이슈를 찾을 수 없습니다.")

            return FinalReviewResponse(
                id=issue.id,
                name=issue.name,
                description=issue.description,
                background=issue.background,
                core_contentions=issue.core_contentions,
                created_at=issue.created_at,
                updated_at=getattr(issue, "updated_at", issue.created_at), # 신규 필드 (없으면 created_at)
                pre_generated_draft=issue.pre_generated_draft,
                sources=sources,
                guideline_checks=guideline_checks,
                ai_opinion=final_state.get("ai_opinion", "의견을 생성할 수 없습니다.")
            )

        except Exception as e:
            logger.error(f"❌ [FinalReview Graph] 실행 중 오류: {e}")
            raise HTTPException(status_code=500, detail=f"품질 검토 중 오류가 발생했습니다: {str(e)}")
