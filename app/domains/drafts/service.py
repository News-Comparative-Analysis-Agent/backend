import os
import json
import time
from typing import List, Optional
from difflib import SequenceMatcher

import google.generativeai as genai
from sqlalchemy.orm import Session
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.domains.drafts.repository import DraftRepository
from app.domains.drafts.schemas import (
    ChatRequest, ChatResponse, ImageItem, 
    SimilarityRequest, SimilarityResponse,
    ArticleInfo, PerspectiveItem, PerspectivesResponse
)

# Gemini 초기 설정
google_api_key = os.getenv("GOOGLE_API_KEY")
if google_api_key:
    genai.configure(api_key=google_api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')
else:
    model = None

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
    async def _stream_generator(self, prompt: str):
        try:
            response = model.generate_content(prompt, stream=True)
            for chunk in response:
                if chunk.text:
                    text_chunk = chunk.text
                    data = json.dumps({"text": text_chunk}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
        except Exception as e:
            error_msg = json.dumps({"text": f"\n\n[Error] 생성 중 오류 발생: {str(e)}"}, ensure_ascii=False)
            yield f"data: {error_msg}\n\n"

    def generate_draft_stream(self, issue_id: int):
        context_text = ""
        
        if issue_id:
            issue = self.repo.get_issue_by_id(issue_id)
            if issue:
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
            self._stream_generator(system_prompt), 
            media_type="text/event-stream"
        )

    # ==========================================
    # 2. AI 챗봇 (초안 첨삭) 로직
    # ==========================================
    def chat_with_ai(self, request: ChatRequest) -> ChatResponse:
        if not model:
            raise HTTPException(status_code=500, detail="Google Gemini API Key is not configured.")

        try:
            system_prompt = """
당신은 기사 작성을 돕는 스마트 AI 어시스턴트입니다.
사용자는 현재 뉴스 기사 초안을 작성하고 있는 기자 또는 작가입니다.

[역할]
1. 사용자의 질문에 친절하고 전문적으로 답변하세요.
2. 'draft_content'가 제공되면, 문맥을 파악하여 피드백을 제공하세요.
3. **중요**: 사용자가 초안 수정을 명시적으로 요청하거나 수정이 필요한 질문을 하면, **초안 전체를 수정한 결과**를 제공해야 합니다.

[출력 형식]
반드시 다음 JSON 형식으로만 응답하세요. 마크다운 코드 블록(` ```json `)을 포함하지 마세요.
{
    "response": "사용자에게 할 말 (한국어)",
    "modified_content": "수정된 전체 초안 내용 (수정 사항이 없으면 null)"
}
            """
            context_message = f"{system_prompt}\n\n[현재 작성 중인 초안]\n{request.draft_content}\n\n"
            
            if request.messages:
                last_user_input = request.messages[-1].content
                full_prompt = context_message + f"[사용자 질문]\n{last_user_input}"
                
                response = model.generate_content(
                    full_prompt,
                    generation_config={"response_mime_type": "application/json"}
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
            print(f"Gemini Chat Error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"AI 응답 생성 중 오류가 발생했습니다: {str(e)}")

    # ==========================================
    # 3. 이미지 추출 로직
    # ==========================================
    def get_issue_images(self, issue_id: int) -> List[ImageItem]:
        articles = self.repo.get_articles_by_issue_with_publisher(issue_id)
        if not articles:
            return []

        images = []
        seen_urls = set()

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
        return images

    # ==========================================
    # 4. 표절/유사도 검사 로직
    # ==========================================
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        if not text1 or not text2:
            return 0.0
        return SequenceMatcher(None, text1, text2).quick_ratio()

    def check_similarity(self, request: SimilarityRequest) -> SimilarityResponse:
        if not request.draft_text.strip():
            return SimilarityResponse(score=0, message="작성된 내용이 없습니다.", status="safe")

        articles = self.repo.get_articles_by_issue(request.issue_id)
        if not articles:
            return SimilarityResponse(score=0, message="비교할 관련 기사가 없습니다.", status="safe")

        max_score = 0.0
        for article in articles:
            sim_summary = self._calculate_similarity(request.draft_text, article.summary or "")
            sim_title = self._calculate_similarity(request.draft_text, article.title or "")
            max_score = max(max_score, sim_summary, sim_title)

        score_percent = int(max_score * 100)
        
        if score_percent < 30:
            status = "safe"
            message = "작성 중인 내용의 유사도가 안전 범위에 있습니다."
        elif score_percent < 60:
            status = "warning"
            message = "일부 내용이 기존 기사와 유사합니다. 인용 표시를 고려하세요."
        else:
            status = "critical"
            message = "기존 기사와 매우 유사합니다. 표절 가능성이 높습니다."

        return SimilarityResponse(
            score=score_percent,
            message=message,
            status=status
        )

    # ==========================================
    # 5. 3가지 진영 관점 분석 로직
    # ==========================================
    async def _summarize_perspective(self, publisher_name: str, articles_text: str) -> str:
        if not articles_text:
            return "관련 기사가 부족하여 분석할 수 없습니다."
            
        prompt = f"""
        당신은 미디어 분석가입니다. 아래 제공된 뉴스 기사들은 '{publisher_name}'의 보도입니다.
        
        [기사 목록]
        {articles_text}
        
        [요청사항]
        위 기사들을 바탕으로, 해당 언론사가 이 이슈를 바라보는 핵심 논점과 스탠스를 1~2문장으로 요약해 주세요.
        - 핵심 인용구문형태 (예: "명분 없는 합당 추진은 결국 내부 권력 투쟁만 표면화시킨 정치적 자해 행위다.") 등으로 작성하면 좋습니다.
        - 분량은 100자 내외.
        """
        try:
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"분석 중 오류 발생: {str(e)}"

    async def analyze_perspectives(self, issue_id: int) -> PerspectivesResponse:
        issue = self.repo.get_issue_by_id(issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="Issue not found")

        articles = self.repo.get_articles_by_issue_with_publisher(issue_id)
        if not articles:
            return PerspectivesResponse(
                issue_id=issue.id,
                issue_name=issue.name,
                perspectives=[]
            )

        grouped_articles = {}
        for art in articles:
            pub_name = art.publisher.name if getattr(art, 'publisher', None) else "알 수 없음"
            if pub_name not in grouped_articles:
                grouped_articles[pub_name] = []
            grouped_articles[pub_name].append(art)
        
        results = []
        for pub_name, arts in grouped_articles.items():
            article_infos = []
            context_text_list = []
            
            for art in arts:
                article_infos.append(ArticleInfo(
                    id=art.id,
                    title=art.title,
                    url=art.url,
                    publisher=pub_name,
                    published_at=art.published_at.strftime("%Y-%m-%d") if art.published_at else ""
                ))
                context_text_list.append(f"- {art.title}: {art.summary or '내용 없음'}")
            
            if arts:
                joined_text = "\n".join(context_text_list)
                summary_text = await self._summarize_perspective(pub_name, joined_text)
            else:
                summary_text = "해당 언론사의 기사가 수집되지 않았습니다."

            results.append(PerspectiveItem(
                publisher=pub_name,
                summary=summary_text,
                articles=article_infos
            ))
            
        return PerspectivesResponse(
            issue_id=issue.id,
            issue_name=issue.name,
            perspectives=results
        )
