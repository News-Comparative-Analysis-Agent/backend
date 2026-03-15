from fastapi import HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict
from datetime import datetime, timezone
from app.domains.issues.repository import IssueRepository
from app.domains.issues.schemas import IssueFeedItem, IssueFeedResponse
from collections import defaultdict

class IssueService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = IssueRepository(db)

    # def get_daily_issues(self, limit: int = 10) -> List[IssueResponse]:
    #     """
    #     실시간 이슈 목록 조회
    #     """
    #     issues = self.repo.get_recent_issues(limit=limit)
        
    #     result = []
    #     for idx, issue in enumerate(issues):
    #         result.append(IssueResponse(
    #             id=issue.id,
    #             name=issue.name,
    #             description=issue.description,
    #             article_count=issue.total_count,
    #             rank=idx + 1,
    #             pre_generated_draft=issue.pre_generated_draft,
    #             created_at=issue.created_at
    #         ))
            
    #     return result

    # def get_daily_trends(self, limit: int = 10) -> List[IssueResponse]:
    #     """
    #     트렌드 이슈 목록 조회
    #     """
    #     issues = self.repo.get_top_issues(limit=limit)
    #
    #     result = []
    #     for idx, issue in enumerate(issues):
    #         result.append(IssueResponse(
    #             id=issue.id,
    #             name=issue.name,
    #             description=issue.description,
    #             article_count=issue.total_count,
    #             rank=idx + 1,
    #             pre_generated_draft=issue.pre_generated_draft,
    #             created_at=issue.created_at
    #         ))
    #
    #     return result

    def get_issue_analysis(self, issue_id: int) -> IssueAnalysisResponse:
        """
        특정 이슈에 대한 고도화된 분석 데이터(메타데이터 + 주장 카드) 제공
        """
        # 1. 이슈 기본 정보 및 분석 메타데이터 조회
        issue = self.repo.get_by_id(issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="해당 이슈를 찾을 수 없습니다.")
    
        # 2. 관련 주장 카드 데이터 조회
        claims = self.repo.get_claims_by_issue(issue_id)
    
        from app.domains.issues.schemas import ClaimCardResponse
        claim_cards = [
            ClaimCardResponse(
                id=c.id,
                press=c.press,
                claim=c.claim,
                evidence=c.evidence,
                url=c.article.url if c.article else None
            ) for c in claims
        ]
    
        return IssueAnalysisResponse(
            id=issue.id,
            name=issue.name,
            description=issue.description,
            background=issue.background,
            core_contentions=issue.core_contentions,
            media_ratio=issue.media_ratio,
            pre_generated_draft=issue.pre_generated_draft,
            created_at=issue.created_at,
            claim_cards=claim_cards
        )

    def get_issue_feed(self, top_count: int = 10, chart_out_count: int = 20) -> IssueFeedResponse:
        """
        피드용 30개 이슈 조회
        - top_issues     : 가장 최근 생성된 top_count개 (최신순 순위 부여)
        - chart_out_issues: 그 이후 chart_out_count개 (차트아웃 시간 포함)
        """
        total = top_count + chart_out_count
        issues = self.repo.get_feed_issues(total=total)

        # TOP 10 경계 기준: 10번째 이슈의 created_at
        boundary_time = None
        if len(issues) >= top_count:
            bt = issues[top_count - 1].created_at
            # naive datetime으로 통일
            if hasattr(bt, 'tzinfo') and bt.tzinfo is not None:
                bt = bt.replace(tzinfo=None)
            boundary_time = bt

        now = datetime.now()
        top_issues: List[IssueFeedItem] = []
        chart_out_issues: List[IssueFeedItem] = []

        for idx, issue in enumerate(issues):
            rank_in_feed = idx + 1  # 전체 리스트 내 순위 (1~30)

            created_at = issue.created_at
            if hasattr(created_at, 'tzinfo') and created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)

            if idx < top_count:
                # ─── TOP 10: 현재 차트에 있는 이슈 ───
                # 1순위 이슈에만 기사 이미지 URL을 첨부
                image_urls = (
                    self.repo.get_image_urls_by_issue(issue.id) if idx == 0 else []
                )
                top_issues.append(IssueFeedItem(
                    id=issue.id,
                    name=issue.name,
                    description=issue.description,
                    article_count=issue.total_count,
                    rank=rank_in_feed,
                    pre_generated_draft=issue.pre_generated_draft,
                    created_at=issue.created_at,
                    is_chart_out=False,
                    image_urls=image_urls,
                ))
            else:
                # ─── 차트아웃 이슈 ───
                # peak_rank: 이 이슈가 한때 가졌던 최고 순위 (현재는 feed 내 순위로 근사)
                peak_rank = rank_in_feed

                # chart_out_minutes: 10위 기준점과 이 이슈 생성 시각 사이의 분 차이
                if boundary_time is not None:
                    diff_minutes = int((boundary_time - created_at).total_seconds() / 60)
                else:
                    diff_minutes = int((now - created_at).total_seconds() / 60)

                chart_out_issues.append(IssueFeedItem(
                    id=issue.id,
                    name=issue.name,
                    description=issue.description,
                    article_count=issue.total_count,
                    rank=rank_in_feed,
                    pre_generated_draft=issue.pre_generated_draft,
                    created_at=issue.created_at,
                    is_chart_out=True,
                    peak_rank=peak_rank,
                    chart_out_minutes=max(0, diff_minutes),
                ))

        return IssueFeedResponse(
            top_issues=top_issues,
            chart_out_issues=chart_out_issues,
        )
