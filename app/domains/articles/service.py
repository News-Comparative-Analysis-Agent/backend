from fastapi import HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Dict
from datetime import date as py_date
from app.domains.articles.models import Article, ArticleBody
from app.domains.publishers.models import Publisher
from app.domains.articles.schemas import ArticleResponse, ArticleDetail, ArticleGroupedResponse
from app.domains.articles.repository import ArticleRepository
from collections import defaultdict

class ArticleService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ArticleRepository(db)

    def get_articles(self, issue_id: Optional[int] = None, date: Optional[str] = None, limit: int = 10) -> List[Article]:
        """기사 목록 조회 (최신순 + 필터링)"""
        target_date = None
        if date:
            try:
                target_date = py_date.fromisoformat(date)
            except ValueError:
                raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다. (YYYY-MM-DD)")
                
        articles = self.repo.get_articles(issue_id=issue_id, target_date=target_date, limit=limit)
        
        # 필드 채우기 (publisher_name, image_url)
        for article in articles:
            if article.publisher:
                article.publisher_name = article.publisher.name
            if article.image_urls and len(article.image_urls) > 0:
                article.image_url = article.image_urls[0]
            
            # 기사 유형 추가
            article.article_type = getattr(article, "article_type", None)
                
        return articles

    def get_grouped_articles(self, days: int = 7) -> ArticleGroupedResponse:
        """최근 N일간의 기사를 날짜별/언론사별로 그룹화하여 조회"""
        articles = self.repo.get_articles_by_date_range(days=days)
        
        # 중첩 데이터 구조: { date: { publisher: [articles] } }
        grouped_data: Dict[str, Dict[str, List[Article]]] = defaultdict(lambda: defaultdict(list))
        
        for article in articles:
            # 필드 채우기 (publisher_name, image_url)
            publisher_name = "기타"
            if article.publisher:
                publisher_name = article.publisher.name
                article.publisher_name = publisher_name
                
            if article.image_urls and len(article.image_urls) > 0:
                article.image_url = article.image_urls[0]
            
            # 기사 유형 추가
            article.article_type = getattr(article, "article_type", None)
                
            date_key = article.published_at.date().isoformat()
            grouped_data[date_key][publisher_name].append(article)
            
        return ArticleGroupedResponse(data=dict({k: dict(v) for k, v in grouped_data.items()}))

    def get_article(self, article_id: int) -> Optional[Article]:
        """기사 상세 조회"""
        article = self.repo.get_article(article_id)
        if article:
            if article.publisher:
                article.publisher_name = article.publisher.name
            if article.image_urls and len(article.image_urls) > 0:
                article.image_url = article.image_urls[0]
            
            # 기사 유형 추가
            article.article_type = getattr(article, "article_type", None)
        return article

    def get_articles_by_issue(self, issue_label_id: int, limit: int = 20) -> List[Article]:
        """이슈 라벨(클러스터)별 기사 목록 조회"""
        articles = self.repo.get_articles_by_issue(issue_label_id=issue_label_id, limit=limit)
        for article in articles:
            article.article_type = getattr(article, "article_type", None)
        return articles

    def get_top_articles_by_publisher(self, limit: int = 10) -> Dict[str, List[Article]]:
        """언론사별 상위(최신) 기사 조회"""
        
        target_publishers = ["한겨레", "경향신문", "조선일보", "동아일보", "연합뉴스"]
        publishers = self.repo.get_publishers_by_names(target_publishers)
        
        result = {}
        for pub in publishers:
            articles = self.repo.get_articles_by_publisher(publisher_id=pub.id, limit=limit)
            
            for i, article in enumerate(articles):
                article.publisher_name = pub.name
                # 1위 기사에 대해서만 대표 이미지 URL 설정
                if i == 0 and article.image_urls and len(article.image_urls) > 0:
                    article.image_url = article.image_urls[0]
                
                # 기사 유형 추가
                article.article_type = getattr(article, "article_type", None)
                
            result[pub.name] = articles
            
        return result

    def save_article_claim(self, issue_id: int, article_id: int, press: str, claim: str, evidence: str):
        """에이전트 1의 추출 결과를 저장합니다."""
        db_claim = self.repo.save_article_claim(issue_id, article_id, press, claim, evidence)
        self.db.commit() # 트랜잭션 관리
        return db_claim

    def get_claims_by_issue(self, issue_id: int):
        """이슈 ID로 저장된 주장 데이터를 조회합니다."""
        return self.repo.get_claims_by_issue(issue_id)
