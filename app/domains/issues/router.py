from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.domains.issues.service import IssueService
from app.domains.issues.schemas import IssueResponse, IssueAnalysisResponse

router = APIRouter()

@router.get("/daily-issues", 
            response_model=List[IssueResponse],
            summary="실시간 속보 이슈 (최신순)",
            description="가장 최근에 생성된 이슈 목록을 반환합니다.")
def get_daily_issues(
    limit: int = Query(10, description="조회할 이슈 개수"),
    db: Session = Depends(get_db)
):
    """
    최근 생성된 이슈 목록 조회
    """
    service = IssueService(db)
    return service.get_daily_issues(limit=limit)

@router.get("/daily-trends", 
            response_model=List[IssueResponse],
            summary="주요 핫 트렌드 (인기순)",
            description="누적 기사 수가 가장 많은 이슈 목록을 반환합니다.")
def get_daily_trends(
    limit: int = Query(10, description="조회할 이슈 개수"),
    db: Session = Depends(get_db)
):
    """
    일별 트렌드 이슈 목록 조회 (기사 수 기준 내림차순)
    """
    service = IssueService(db)
    return service.get_daily_trends(limit=limit)

@router.get("/{issue_id}/analysis",
            response_model=IssueAnalysisResponse,
            summary="이슈 상세 분석 (언론사별 요약 및 성향)",
            description="특정 이슈에 포함된 기사들을 언론사별로 그룹화하여 AI 요약과 정치 성향 등의 상세 분석 정보를 제공합니다.")
def get_issue_analysis(
    issue_id: int,
    db: Session = Depends(get_db)
):
    """
    특정 이슈의 언론사별 분석 데이터 조회
    """
    service = IssueService(db)
    return service.get_issue_analysis(issue_id)
