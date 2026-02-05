from sqlalchemy.orm import Session
from typing import List
from app.domains.issues.repository import IssueRepository
from app.domains.issues.schemas import IssueResponse
from fastapi import HTTPException

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
                article_count=issue.total_count,
                rank=idx + 1,
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
                article_count=issue.total_count,
                rank=idx + 1,
                created_at=issue.created_at
            ))
            
        return result
