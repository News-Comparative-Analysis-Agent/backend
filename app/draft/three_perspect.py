from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import google.generativeai as genai
import os
from app.core.database import get_db
from app.domains.issues.models import IssueLabel
from app.domains.articles.models import Article
from app.domains.publishers.models import Publisher

router = APIRouter()

# Gemini Configuration
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel('gemini-2.0-flash')

# Publisher Stance Mapping
# User requested specific mapping:
# Progressive: 한겨레, 경향신문
# Conservative: 조선일보, 동아일보
# Neutral: 연합뉴스
PUBLISHER_STANCE = {
    "한겨레": "progressive",
    "경향신문": "progressive",
    "조선일보": "conservative",
    "동아일보": "conservative",
    "연합뉴스": "neutral",
    # Fallback or additional mappings can be added here
}

STANCE_KOREAN = {
    "progressive": "진보",
    "conservative": "보수",
    "neutral": "중립",
    "unknown": "기타"
}

class ArticleInfo(BaseModel):
    id: int
    title: str
    url: str
    publisher: str
    published_at: str

class PerspectiveItem(BaseModel):
    stance: str       # progressive, conservative, neutral
    stance_kr: str    # 진보, 보수, 중립
    summary: str      # Gemini analysis result
    articles: List[ArticleInfo]

class PerspectivesResponse(BaseModel):
    issue_id: int
    issue_name: str
    perspectives: List[PerspectiveItem]

async def summarize_perspective(stance_name: str, articles_text: str) -> str:
    if not articles_text:
        return "관련 기사가 부족하여 분석할 수 없습니다."
        
    prompt = f"""
    당신은 미디어 분석가입니다. 아래 제공된 뉴스 기사들은 '{stance_name}' 성향을 가진 언론사들의 보도입니다.
    
    [기사 목록]
    {articles_text}
    
    [요청사항]
    위 기사들을 바탕으로, 해당 성향(진영)에서 이 이슈를 바라보는 핵심 관점과 논리를 2~3문장으로 요약해 주세요.
    - 구체적인 근거를 포함할 것.
    - '~라고 주장함', '~를 강조함' 등의 건조한 어조 사용.
    - 분량은 100자 내외.
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"분석 중 오류 발생: {str(e)}"

@router.get("/perspectives/{issue_id}", response_model=PerspectivesResponse)
async def analyze_perspectives(issue_id: int, db: Session = Depends(get_db)):
    """
    특정 이슈에 대해 진보/보수/중립 언론사의 관점을 분석하여 반환합니다.
    """
    # 1. Fetch Issue
    issue = db.query(IssueLabel).filter(IssueLabel.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # 2. Fetch Articles with Publisher
    articles = db.query(Article).join(Publisher).filter(Article.issue_label_id == issue_id).all()
    
    if not articles:
        return PerspectivesResponse(
            issue_id=issue.id,
            issue_name=issue.name,
            perspectives=[]
        )

    # 3. Group by Stance
    grouped_articles = {
        "progressive": [],
        "conservative": [],
        "neutral": []
        # "unknown": [] # We can focus on the 3 requested
    }

    for art in articles:
        pub_name = art.publisher.name
        stance = PUBLISHER_STANCE.get(pub_name)
        
        # Handle exact string matching carefully, maybe strip? assuming clear data for now
        if stance in grouped_articles:
            grouped_articles[stance].append(art)
    
    # 4. Generate Summaries using Gemini
    results = []
    
    # Order: Progressive -> Neutral -> Conservative (as requested in the image/prompt usually partial ordering)
    # User image: Progressive (Blue), Neutral (Gray), Conservative (Red)
    target_stances = ["progressive", "neutral", "conservative"]
    
    for stance in target_stances:
        arts = grouped_articles[stance]
        
        article_infos = []
        context_text_list = []
        
        for art in arts:
            article_infos.append(ArticleInfo(
                id=art.id,
                title=art.title,
                url=art.url,
                publisher=art.publisher.name,
                published_at=art.published_at.strftime("%Y-%m-%d")  # Basic formatting
            ))
            context_text_list.append(f"- [{art.publisher.name}] {art.title}: {art.summary or '내용 없음'}")
        
        # summary generation
        if arts:
             joined_text = "\n".join(context_text_list)
             summary_text = await summarize_perspective(STANCE_KOREAN[stance], joined_text)
        else:
            summary_text = "해당 관점의 기사가 수집되지 않았습니다."

        results.append(PerspectiveItem(
            stance=stance,
            stance_kr=STANCE_KOREAN[stance],
            summary=summary_text,
            articles=article_infos
        ))
        
    return PerspectivesResponse(
        issue_id=issue.id,
        issue_name=issue.name,
        perspectives=results
    )
