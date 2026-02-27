from sqlalchemy.orm import Session
from typing import List, Optional, Dict
from app.domains.articles.models import Article, ArticleBody
from app.domains.publishers.models import Publisher
from app.domains.articles.schemas import ArticleResponse, ArticleDetail

class ArticleService:
    def __init__(self, db: Session):
        self.db = db

    def get_articles(self, issue_id: Optional[int] = None, limit: int = 20) -> List[Article]:
        """기사 목록 조회 (최신순)"""
        query = self.db.query(Article)
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

    def get_top_articles_by_publisher(self, limit: int = 10) -> Dict[str, List[Article]]:
        """5개 주요 언론사별 상위(최신) 기사 조회"""
        target_publishers = ["한겨레", "경향신문", "조선일보", "동아일보", "연합뉴스"]
        publishers = self.db.query(Publisher).filter(Publisher.name.in_(target_publishers)).all()
        
        result = {}
        for pub in publishers:
            articles = self.db.query(Article).filter(
                Article.publisher_id == pub.id
            ).order_by(Article.published_at.desc()).limit(limit).all()
            
            for article in articles:
                article.publisher_name = pub.name
                
            result[pub.name] = articles
            
        return result
