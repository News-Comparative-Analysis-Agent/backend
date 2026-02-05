from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.domains.keywordrelation.service import KeywordRelationService
from app.domains.keywordrelation.schemas import GraphData, KeywordMentionResponse

router = APIRouter()

@router.get("/keyword-cluster", 
            response_model=GraphData,
            summary="상위 10개 이슈 키워드",
            description="상위 10개 주요 이슈의 키워드 관계를 통합하여 뉴스 전체의 맥락을 네트워크 그래프로 제공합니다.")
def get_trend_network(
    limit: int = Query(10, description="분석에 포함할 이슈 개수"),
    db: Session = Depends(get_db)
):
    """
    뉴스 키워드 트렌드 네트워크 조회 API
    """
    service = KeywordRelationService(db)
    return service.get_trend_graph(limit=limit)

@router.get("/graph", 
            response_model=GraphData,
            summary="키워드 연관성 분석",
            description="특정 키워드를 클릭했을 때, 해당 키워드와 직접적으로 연관된 다른 키워드들과의 관계망을 반환합니다.")
def get_keyword_graph(
    keyword: str = Query(..., description="연관성을 조회할 중심 키워드"),
    db: Session = Depends(get_db)
):
    """
    특정 키워드 중심의 연관 네트워크 조회 API
    """
    service = KeywordRelationService(db)
    return service.get_keyword_graph(keyword=keyword)

@router.get("/keyword-mentions", 
            response_model=KeywordMentionResponse,
            summary="키워드 시계열 언급량 추이",
            description="특정 키워드가 뉴스에서 언급된 횟수(관계 빈도 합계)의 시계열 추이를 반환합니다.")
def get_keyword_mentions(
    keyword: str = Query(..., description="조회할 키워드"),
    db: Session = Depends(get_db)
):
    """
    특정 키워드 언급량 추이 조회 API
    """
    service = KeywordRelationService(db)
    return service.get_keyword_mentions(keyword=keyword)