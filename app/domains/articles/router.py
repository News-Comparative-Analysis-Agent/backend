from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.domains.articles.service import ArticleService
from app.domains.articles.schemas import ArticleResponse, ArticleDetail

router = APIRouter()

@router.get("/search", response_model=List[ArticleResponse])
def search_articles(
    topic_id: Optional[int] = Query(None, description="필터링할 토픽 ID"), 
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """
    기사 목록/검색 조회 API
    - topic_id가 있으면 해당 토픽의 기사만 조회
    """
    service = ArticleService(db)
    articles = service.get_articles(topic_id=topic_id, limit=limit)
    
    # Response 변환 (publisher_name 매핑 등은 여기서 하거나 Schema에서 처리)
    return articles

@router.get("/{article_id}", response_model=ArticleDetail)
def get_article_detail(article_id: int, db: Session = Depends(get_db)):
    """
    기사 상세 조회 API
    - 본문(content) 포함
    """
    service = ArticleService(db)
    article = service.get_article(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    # 본문 데이터 매핑
    response = ArticleDetail.model_validate(article)
    if article.body:
        response.content = article.body.raw_content
        
    return response
