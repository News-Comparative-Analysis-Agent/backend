from sqlalchemy.orm import Session
from typing import List
from app.domains.issues.models import IssueLabel
from app.domains.issues.schemas import IssueResponse
from fastapi import HTTPException

class IssueService:
    def __init__(self, db: Session):
        self.db = db

    def get_daily_issues(self, limit: int = 10) -> List[IssueResponse]:
        """
        실시간 이슈 목록 조회
        - 최근 생성된(created_at) 이슈를 우선으로 하며, 그 중 기사 수가 많은 순으로 정렬합니다.
        - '지금 막 터진' 뉴스들을 보여주기에 적합합니다.
        """
        issues = self.db.query(IssueLabel)\
            .order_by(IssueLabel.created_at.desc(), IssueLabel.total_count.desc())\
            .limit(limit)\
            .all()
        
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
        - 누적 기사 수(total_count)가 가장 많은 순서대로 정렬합니다.
        - 현재 가장 화제가 되고 있는 굵직한 주제들을 보여주기에 적합합니다.
        """
        issues = self.db.query(IssueLabel)\
            .order_by(IssueLabel.total_count.desc())\
            .limit(limit)\
            .all()
        
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
