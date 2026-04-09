from fastapi import HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict
from datetime import datetime, timezone
from app.domains.issues.repository import IssueRepository
from app.domains.issues.schemas import IssueFeedItem, IssueFeedResponse, IssueAnalysisResponse, IssueDraftResponse, ClaimCardResponse
from collections import defaultdict

class IssueService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = IssueRepository(db)
        
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
                title=c.article.title if c.article else "",
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
            created_at=issue.created_at,
            claim_cards=claim_cards
        )

    def get_issue_draft(self, issue_id: int) -> IssueDraftResponse:
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
                title=c.article.title if c.article else "",
                claim=c.claim,
                evidence=c.evidence,
                url=c.article.url if c.article else None
            ) for c in claims
        ]
    
        return IssueDraftResponse(
            id=issue.id,
            name=issue.name,
            description=issue.description,
            background=issue.background,
            core_contentions=issue.core_contentions,
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

        # 전체 이슈의 이미지 URL을 일괄 조회
        issue_ids = [issue.id for issue in issues]
        image_urls_map = self.repo.get_image_urls_by_issue_ids(issue_ids)

        for idx, issue in enumerate(issues):
            rank_in_feed = idx + 1  # 전체 리스트 내 순위 (1~30)

            created_at = issue.created_at
            if hasattr(created_at, 'tzinfo') and created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)

            # 모든 이슈에 이미지 URL 추가 (기본값 빈 리스트)
            image_urls = image_urls_map.get(issue.id, [])

            if idx < top_count:
                # ─── TOP 10: 현재 차트에 있는 이슈 ───
                top_issues.append(IssueFeedItem(
                    id=issue.id,
                    name=issue.name,
                    description=issue.description,
                    article_count=issue.total_count,
                    rank=rank_in_feed,
                    created_at=created_at,
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
                    created_at=created_at,
                    is_chart_out=True,
                    peak_rank=peak_rank,
                    chart_out_minutes=max(0, diff_minutes),
                    image_urls=image_urls,
                ))

        return IssueFeedResponse(
            top_issues=top_issues,
            chart_out_issues=chart_out_issues,
        )

    def get_issue_timeline(self, issue_id: int):
        """특정 이슈와 타이틀이 유사한 이슈들을 찾고 그 중 과거의 이슈들을 타임라인으로 반환합니다."""
        target_issue = self.repo.get_by_id(issue_id)
        if not target_issue:
            raise HTTPException(status_code=404, detail="해당 이슈를 찾을 수 없습니다.")

        # 최근 이슈 N개 조회 (성능을 위해 제한)
        recent_issues = self.repo.get_recent_issues_for_timeline(limit=400)

        import difflib
        
        # 유사도 필터링
        similar_issues = []
        for issue in recent_issues:
            # 타임라인에는 과거부터 현재까지 발생한 이슈가 포함됩니다.
            # difflib.SequenceMatcher 로 글자 기반 유사도 측정 (한국어 텍스트에 효과적임)
            ratio = difflib.SequenceMatcher(None, target_issue.name, issue.name).ratio()
            
            # 1. 대상 이슈 이름에 부분 문자열이 완전히 포함
            # 2. 혹은 글자 유사도가 55% 이상인 경우 타임라인으로 간주
            if (target_issue.name in issue.name or 
                issue.name in target_issue.name or 
                ratio >= 0.55):
                similar_issues.append(issue)

        # 시간순(과거->최신) 정렬
        similar_issues.sort(key=lambda x: x.created_at)

        # 이미지 URL 일괄 조회
        issue_ids = [iss.id for iss in similar_issues]
        image_urls_map = self.repo.get_image_urls_by_issue_ids(issue_ids)
        
        from app.domains.issues.schemas import IssueTimelineItem, IssueTimelineResponse
        
        timeline_items = []
        for issue in similar_issues:
            created_at = issue.created_at
            if hasattr(created_at, 'tzinfo') and created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)
                
            image_urls = image_urls_map.get(issue.id, [])
            
            timeline_items.append(IssueTimelineItem(
                id=issue.id,
                name=issue.name,
                article_count=issue.total_count,
                created_at=created_at,
                image_urls=image_urls,
            ))

        return IssueTimelineResponse(
            target_issue_id=target_issue.id,
            target_issue_name=target_issue.name,
            timeline=timeline_items
        )
