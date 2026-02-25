from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from difflib import SequenceMatcher
from app.core.database import get_db
from app.domains.articles.models import Article

router = APIRouter()


def calculate_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity ratio between two texts using SequenceMatcher.
    Returns a float between 0.0 and 1.0.
    """
    if not text1 or not text2:
        return 0.0
    return SequenceMatcher(None, text1, text2).quick_ratio()

@router.post("/similarity", response_model=SimilarityResponse)
async def check_similarity(request: SimilarityRequest, db: Session = Depends(get_db)):
    """
    Checks the similarity of the draft text against related articles for a given issue.
    Returns the maximum similarity score found.
    """
    if not request.draft_text.strip():
        return SimilarityResponse(score=0, message="작성된 내용이 없습니다.", status="safe")

    # 1. Fetch related articles
    # We compare against summaries for efficiency, or raw body if available and needed.
    # Comparing against summaries is a good proxy for "plagiarism of core ideas" or "copy-pasting abstract".
    # If ArticleBody is available, we could join and check that too, but let's start with summary/title for speed.
    articles = db.query(Article).filter(Article.issue_label_id == request.issue_id).all()
    
    if not articles:
        return SimilarityResponse(score=0, message="비교할 관련 기사가 없습니다.", status="safe")

    max_score = 0.0
    
    for article in articles:
        # Check against summary
        sim_summary = calculate_similarity(request.draft_text, article.summary)
        # Check against title (less likely to be high, but good to check)
        sim_title = calculate_similarity(request.draft_text, article.title)
        
        # Keep the max
        max_score = max(max_score, sim_summary, sim_title)

    # Convert to percentage integer
    score_percent = int(max_score * 100)
    
    # Determine status and message
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
