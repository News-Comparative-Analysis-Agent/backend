from sqlalchemy.orm import Session
from typing import List
from app.domains.issues.models import IssueLabel
from app.domains.articles.models import Article
from app.domains.publishers.models import Publisher

class IssueRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_recent_issues(self, limit: int = 10) -> List[IssueLabel]:
        """최근 생성일 및 기사 수 기준 정렬된 이슈 조회"""
        return self.db.query(IssueLabel)\
            .order_by(IssueLabel.created_at.desc(), IssueLabel.total_count.desc())\
            .limit(limit)\
            .all()

    def get_top_issues(self, limit: int = 10) -> List[IssueLabel]:
        """기사 수 기준 상위 이슈 조회"""
        return self.db.query(IssueLabel)\
            .order_by(IssueLabel.total_count.desc())\
            .limit(limit)\
            .all()

    def get_by_id(self, issue_id: int) -> IssueLabel:
        """ID로 이슈 상세 조회"""
        return self.db.query(IssueLabel).filter(IssueLabel.id == issue_id).first()

    def get_articles_with_publisher(self, issue_id: int) -> List[Article]:
        """특정 이슈에 속한 기사들을 언론사 정보와 함께 조회"""
        return self.db.query(Article)\
            .join(Publisher)\
            .filter(Article.issue_label_id == issue_id)\
            .all()
