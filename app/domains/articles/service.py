from sqlalchemy.orm import Session
from typing import List, Optional
from app.domains.articles.models import Article, ArticleBody
from app.domains.articles.schemas import ArticleResponse, ArticleDetail

class ArticleService:
    def __init__(self, db: Session):
        self.db = db

    def get_articles(self, topic_id: Optional[int] = None, limit: int = 20) -> List[Article]:
        """기사 목록 조회 (최신순)"""
        query = self.db.query(Article)
        if topic_id:
            query = query.filter(Article.topic_id == topic_id)
        
        return query.order_by(Article.published_at.desc()).limit(limit).all()

    def get_article(self, article_id: int) -> Optional[Article]:
        """기사 상세 조회"""
        return self.db.query(Article).filter(Article.id == article_id).first()
