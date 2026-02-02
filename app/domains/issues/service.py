from sqlalchemy.orm import Session
from typing import List
from app.domains.issues.models import IssueLabel

from app.domains.issues.schemas import IssueResponse

class IssueService:
    def __init__(self, db: Session):
        self.db = db

    def get_daily_trends(self, limit: int = 10) -> List[IssueResponse]:
        """
        일별 트렌드 이슈 목록 조회 (기사 수 기준 내림차순)
        """
        # 1. 기사 수(total_count) 기준으로 상위 이슈 조회
        issues = self.db.query(IssueLabel)\
            .order_by(IssueLabel.total_count.desc())\
            .limit(limit)\
            .all()
        
        result = []
        for idx, issue in enumerate(issues):
            # 4. 응답 객체 생성
            result.append(IssueResponse(
                id=issue.id,
                name=issue.name,
                article_count=issue.total_count,
                rank=idx + 1,
                created_at=issue.created_at
            ))
            
        return result
