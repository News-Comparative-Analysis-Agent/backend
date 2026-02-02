from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.domains.issues.service import IssueService
from app.domains.issues.schemas import IssueResponse

router = APIRouter()

@router.get("/daily-trends", response_model=List[IssueResponse])
def get_daily_trends(
    limit: int = Query(10, description="조회할 이슈 개수"),
    db: Session = Depends(get_db)
):
    """
    일별 트렌드 이슈 조회 API
    - 기사 수가 많은 순서대로 랭킹과 함께 반환합니다.
    """
    service = IssueService(db)
    return service.get_daily_trends(limit=limit)
