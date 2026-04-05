from sqlalchemy.orm import Session, joinedload
from app.domains.articles.models import Article
from app.domains.issues.models import IssueLabel
from app.domains.publishers.models import Publisher
from typing import List, Optional

class DraftRepository:
    
    #기사 작성(Draft) 과정에서 필요한 데이터베이스 조회 로직을 전담합니다.
    
    def __init__(self, db: Session):
        self.db = db

    def get_issue_by_id(self, issue_id: int) -> Optional[IssueLabel]:
        """특정 이슈를 ID로 조회합니다."""
        return self.db.query(IssueLabel).filter(IssueLabel.id == issue_id).first()

    def get_articles_by_issue_with_publisher(self, issue_id: int, limit: int = None) -> List[Article]:
        """특정 이슈에 속한 기사들을 언론사 정보와 함께 조회합니다. (Join 수행)"""
        query = self.db.query(Article).join(Publisher).filter(Article.issue_label_id == issue_id)
        if limit:
            query = query.limit(limit)
        return query.all()

    def get_articles_by_issue(self, issue_id: int) -> List[Article]:
        """특정 이슈에 속한 기사들만 단순 조회합니다."""
        return self.db.query(Article).filter(Article.issue_label_id == issue_id).all()

    def get_articles_meta_by_issue(self, issue_id: int) -> List[Article]:
        """
        최종 검토용: 이슈에 속한 기사들의 제목, URL, 언론사 정보 및 본문을 조회합니다.
        (기사 본문 원문 비교를 위해 body도 eager load 추가)
        """
        return (
            self.db.query(Article)
            .options(joinedload(Article.publisher), joinedload(Article.body))
            .filter(Article.issue_label_id == issue_id)
            .order_by(Article.published_at.desc())
            .all()
        )

    def get_claims_by_issue(self, issue_id: int):
        """특정 이슈에 속한 모든 주장 카드 조회"""
        from app.domains.articles.models import ArticleClaim
        return self.db.query(ArticleClaim)\
            .filter(ArticleClaim.issue_id == issue_id)\
            .all()
