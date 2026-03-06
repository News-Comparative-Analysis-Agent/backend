
from sqlalchemy.orm import Session
from typing import List, Optional
from app.domains.articles.models import Article, ArticleClaim

class ArticleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_articles(self, limit: int = 20) -> List[Article]:
        """기사 목록 조회 (최신순)"""
        query = self.db.query(Article)
        
        return query.order_by(Article.published_at.desc()).limit(limit).all()

    def get_article(self, article_id: int) -> Optional[Article]:
        """기사 상세 조회"""
        return self.db.query(Article).filter(Article.id == article_id).first()

    def get_articles_by_issue(self, issue_label_id: int, limit: int = 20) -> List[Article]:
        """이슈 라벨(클러스터)별 기사 목록 조회"""
        return self.db.query(Article).filter(
            Article.issue_label_id == issue_label_id
        ).order_by(Article.published_at.desc()).limit(limit).all()

    def get_publishers_by_names(self, names: List[str]):
        """언론사명 리스트로 언론사 목록 조회"""
        from app.domains.publishers.models import Publisher
        return self.db.query(Publisher).filter(Publisher.name.in_(names)).all()

    def save_article_claim(self, issue_id: int, article_id: int, press: str, claim: str, evidence: str) -> ArticleClaim:
        """에이전트 1이 추출한 주장 데이터를 저장합니다."""
        db_claim = ArticleClaim(
            issue_id=issue_id,
            article_id=article_id,
            press=press,
            claim=claim,
            evidence=evidence
        )
        self.db.add(db_claim)
        return db_claim

    def get_claims_by_issue(self, issue_id: int) -> list[ArticleClaim]:
        """이슈 ID에 해당하는 모든 주장 데이터를 조회합니다."""
        return self.db.query(ArticleClaim).filter(ArticleClaim.issue_id == issue_id).all()

    def get_articles_by_publisher(self, publisher_id: int, limit: int = 10) -> List[Article]:
        """언론사별 기사 목록 조회"""
        return self.db.query(Article).filter(
            Article.publisher_id == publisher_id
        ).order_by(Article.published_at.desc()).limit(limit).all()