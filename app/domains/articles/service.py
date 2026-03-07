from sqlalchemy.orm import Session
from typing import List, Optional, Dict
from app.domains.articles.models import Article, ArticleBody
from app.domains.publishers.models import Publisher
from app.domains.articles.schemas import ArticleResponse, ArticleDetail
from app.domains.articles.repository import ArticleRepository

class ArticleService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ArticleRepository(db)

    def get_articles(self, issue_id: Optional[int] = None, limit: int = 10) -> List[Article]:
        """기사 목록 조회 (최신순)"""
        return self.repo.get_articles(issue_id=issue_id, limit=limit)

    def get_article(self, article_id: int) -> Optional[Article]:
        """기사 상세 조회"""
        return self.repo.get_article(article_id)

    def get_articles_by_issue(self, issue_label_id: int, limit: int = 20) -> List[Article]:
        """이슈 라벨(클러스터)별 기사 목록 조회"""
        return self.repo.get_articles_by_issue(issue_label_id=issue_label_id, limit=limit)

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
