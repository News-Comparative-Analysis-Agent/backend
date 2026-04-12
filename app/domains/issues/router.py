from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.domains.issues.service import IssueService
from app.domains.issues.schemas import (
    IssueFeedResponse, IssueAnalysisResponse, IssueDraftResponse, 
    IssueTimelineResponse, IssueGroupedResponse, IssueFeedLegacyResponse
)

router = APIRouter()

@router.get("/daily-issues",
            response_model=IssueFeedResponse,
            summary="날짜별 이슈 피드 조회",
            description="""
지정된 날짜에 생성된 이슈들을 중요도(언론사 수, 기사 수) 순으로 정렬하여 반환합니다.
날짜가 지정되지 않으면 현재 날짜(KST)의 이슈를 반환합니다.
""")
def get_issue_feed(
    date: str = Query(None, description="조회할 날짜 (YYYY-MM-DD)"),
    limit: int = Query(30, description="최대 조회 개수"),
    db: Session = Depends(get_db)
):
    """
    이슈 피드 조회 (날짜별)
    """
    service = IssueService(db)
    return service.get_issue_feed(date_str=date, total=limit)

@router.get("/feed",
            response_model=IssueFeedLegacyResponse,
            summary="레거시 이슈 피드 (TOP 10  차트아웃 20개)",
            description="""
총 30개의 이슈를 두 섹션으로 나눠 반환합니다.

- **top_issues**: 가장 최근에 생성된 이슈 10개 (최신순, rank 1~10)
- **chart_out_issues**: 그 다음 20개 이슈 (OUT 뱃지, `peak_rank` 최고 순위, `chart_out_minutes` 밀려난 경과 시간(분))
""")
def get_issue_feed_legacy(
    top_count: int = Query(10, description="TOP 이슈 개수"),
    chart_out_count: int = Query(20, description="차트아웃 이슈 개수"),
    db: Session = Depends(get_db)
):
    """
    레거시 이슈 피드 조회 (최신 10개  차트아웃 20개)
    """
    service = IssueService(db)
    return service.get_issue_feed_legacy(top_count=top_count, chart_out_count=chart_out_count)

@router.get("/grouped",
            response_model=IssueGroupedResponse,
            summary="최근 N일간의 이슈 날짜별 그룹화 조회",
            description="최근 N일 동안 발생한 이슈들을 날짜별로 묶어서 반환합니다. 메인 타임라인 구성에 적합합니다.")
def get_grouped_issues(
    days: int = Query(7, description="조회할 기간 (일 단위)"),
    db: Session = Depends(get_db)
):
    """
    이슈 그룹화 조회 (최근 N일)
    """
    service = IssueService(db)
    return service.get_grouped_issues(days=days)

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


@router.get("/{issue_id}/draft",
            response_model=IssueDraftResponse,
            summary="이슈 초안 보기 (AI 생성 초안 포함)",
            description="특정 이슈의 기본 분석 정보와 AI가 사전 생성한 초안 내용을 함께 반환합니다.")
def get_issue_draft(
    issue_id: int,
    db: Session = Depends(get_db)
):
    """
    특정 이슈의 초안 데이터 조회
    """
    service = IssueService(db)
    return service.get_issue_draft(issue_id)


@router.get("/{issue_id}/timeline",
            response_model=IssueTimelineResponse,
            summary="특정 이슈의 과거/최신 타임라인 조회",
            description="특정 이슈와 관련된(이름이 유사한) 이슈들을 시간순으로 정렬하여 타임라인 형태로 제공합니다.")
def get_issue_timeline(
    issue_id: int,
    db: Session = Depends(get_db)
):
    """
    특정 이슈의 시간순 타임라인 조회
    """
    service = IssueService(db)
    return service.get_issue_timeline(issue_id)


@router.delete("/{issue_id}",
               status_code=204,
               summary="이슈 삭제 (연관 데이터 연쇄 삭제)",
               description="특정 이슈와 그에 속한 모든 기사, 기사 본문, 분석 데이터를 영구적으로 삭제합니다.")
def delete_issue(
    issue_id: int,
    db: Session = Depends(get_db)
):
    """
    이슈 삭제 API
    """
    service = IssueService(db)
    service.delete_issue(issue_id)
    return None

