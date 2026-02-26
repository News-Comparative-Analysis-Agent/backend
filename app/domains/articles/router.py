from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict
from app.core.database import get_db
from app.domains.articles.service import ArticleService
from app.domains.articles.schemas import ArticleResponse, ArticleDetail

router = APIRouter()

@router.get("/top-by-publisher", 
            response_model=Dict[str, List[ArticleResponse]],
            summary="언론사별 상위 기사 조회",
            description="5개 주요 언론사별로 최신 기사를 10개씩 묶어서 조회합니다.")
def get_top_by_publisher(
    limit: int = Query(10, description="각 언론사별 조회할 최대 기사 개수"), 
    db: Session = Depends(get_db)):
    """
    각 언론사별(한겨레, 경향, 조선, 동아, 연합) 최근 기사를 가져옵니다.
    프론트엔드에서 그대로 각 언론사별 리스트를 뿌릴 수 있습니다.
    """
    service = ArticleService(db)
    return service.get_top_articles_by_publisher(limit=limit)

@router.get("/search", 
            response_model=List[ArticleResponse],
            summary="기사 목록 검색",
            description="이슈(Issue) ID를 기반으로 관련 기사 목록을 조회합니다.")
def search_articles(
    issue_id: Optional[int] = Query(None, description="필터링할 이슈(소주제) ID"),
    limit: int = Query(20, description="최대 조회 개수"),
    db: Session = Depends(get_db)
):
    """
    기사 목록을 검색 조건에 따라 조회합니다.
    - **issue_id**가 있을 경우: 해당 이슈(클러스터)의 기사 반환
    - 없을 경우: 전체 기사 최신순 반환
    """
    service = ArticleService(db)
    articles = service.get_articles(issue_id=issue_id, limit=limit)
    
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
