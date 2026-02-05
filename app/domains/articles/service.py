from sqlalchemy.orm import Session
from typing import List, Optional
from app.domains.articles.models import Article, ArticleBody
from app.domains.articles.schemas import ArticleResponse, ArticleDetail

class ArticleService:
    def __init__(self, db: Session):
        self.db = db

    def get_articles(self, topic_id: Optional[int] = None, issue_id: Optional[int] = None, limit: int = 20) -> List[Article]:
        """기사 목록 조회 (최신순)"""
        query = self.db.query(Article)
        if topic_id:
            query = query.filter(Article.topic_id == topic_id)
        if issue_id:
            query = query.filter(Article.issue_label_id == issue_id)
        
        return query.order_by(Article.published_at.desc()).limit(limit).all()

    def get_article(self, article_id: int) -> Optional[Article]:
        """기사 상세 조회"""
        return self.db.query(Article).filter(Article.id == article_id).first()

    def get_articles_by_issue(self, issue_label_id: int, limit: int = 20) -> List[Article]:
        """이슈 라벨(클러스터)별 기사 목록 조회"""
        return self.db.query(Article).filter(
            Article.issue_label_id == issue_label_id
        ).order_by(Article.published_at.desc()).limit(limit).all()
