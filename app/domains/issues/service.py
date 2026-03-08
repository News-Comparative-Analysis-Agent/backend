from sqlalchemy.orm import Session
from typing import List, Dict
from app.domains.issues.repository import IssueRepository
from app.domains.issues.schemas import IssueResponse, IssueAnalysisResponse
from app.domains.articles.schemas import ArticleResponse
from app.domains.publishers.schemas import PublisherAnalysis
from fastapi import HTTPException
from collections import defaultdict

class IssueService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = IssueRepository(db)

    def get_daily_issues(self, limit: int = 10) -> List[IssueResponse]:
        """
        실시간 이슈 목록 조회
        """
        issues = self.repo.get_recent_issues(limit=limit)
        
        result = []
        for idx, issue in enumerate(issues):
            result.append(IssueResponse(
                id=issue.id,
                name=issue.name,
                description=issue.description,
                article_count=issue.total_count,
                rank=idx + 1,
                pre_generated_draft=issue.pre_generated_draft,
                created_at=issue.created_at
            ))
            
        return result

    def get_daily_trends(self, limit: int = 10) -> List[IssueResponse]:
        """
        트렌드 이슈 목록 조회
        """
        issues = self.repo.get_top_issues(limit=limit)
        
        result = []
        for idx, issue in enumerate(issues):
            result.append(IssueResponse(
                id=issue.id,
                name=issue.name,
                description=issue.description,
                article_count=issue.total_count,
                rank=idx + 1,
                pre_generated_draft=issue.pre_generated_draft,
                created_at=issue.created_at
            ))
            
        return result

    def get_issue_analysis(self, issue_id: int) -> IssueAnalysisResponse:
        """
        특정 이슈에 대한 고도화된 분석 데이터(메타데이터 + 주장 카드) 제공
        """
        # 1. 이슈 기본 정보 및 분석 메타데이터 조회
        issue = self.repo.get_by_id(issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="Issue not found")

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
