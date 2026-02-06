from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.domains.articles.service import ArticleService
from app.domains.articles.schemas import ArticleResponse, ArticleDetail

router = APIRouter()

@router.get("/search", 
            response_model=List[ArticleResponse],
            summary="기사 목록 검색",
            description="주제(Topic) 또는 이슈(Issue) ID를 기반으로 관련 기사 목록을 조회합니다.")
def search_articles(
    topic_id: Optional[int] = Query(None, description="필터링할 토픽(대주제) ID"), 
    issue_id: Optional[int] = Query(None, description="필터링할 이슈(소주제) ID"),
    limit: int = Query(20, description="최대 조회 개수"),
    db: Session = Depends(get_db)
):
    """
    기사 목록을 검색 조건에 따라 조회합니다.
    - **topic_id**만 보낼 경우: 해당 주제의 모든 기사 반환
    - **issue_id**만 보낼 경우: 해당 이슈(클러스터)의 기사 반환
    - 둘 다 없을 경우: 전체 기사 최신순 반환
    """
    service = ArticleService(db)
    articles = service.get_articles(topic_id=topic_id, issue_id=issue_id, limit=limit)
    
    # Response 변환 (publisher_name 매핑 등은 여기서 하거나 Schema에서 처리)
    return articles

@router.get("/{article_id}", 
            response_model=ArticleDetail,
            summary="기사 상세 조회",
            description="기사 ID를 통해 본문 내용을 포함한 상세 정보를 조회합니다.")
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
