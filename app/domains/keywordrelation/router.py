from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.domains.keywordrelation.service import KeywordRelationService
from app.domains.keywordrelation.schemas import GraphData

router = APIRouter()

@router.get("/trend-graph", 
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
