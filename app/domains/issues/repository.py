from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List
from app.domains.issues.models import IssueLabel
from app.domains.articles.models import Article
from app.domains.publishers.models import Publisher

from datetime import datetime

class IssueRepository:
    def __init__(self, db: Session):
        self.db = db

    # def get_recent_issues(self, limit: int = 10) -> List[IssueLabel]:
    #     """오늘 생성된 이슈를 기사 수 기준(인기순)으로 정렬하여 조회"""
    #     today = datetime.now().date()
    #     return self.db.query(IssueLabel)\
    #         .filter(func.date(IssueLabel.created_at) == today)\
    #         .order_by(IssueLabel.total_count.desc())\
    #         .limit(limit)\
    #         .all()

    # def get_top_issues(self, limit: int = 10) -> List[IssueLabel]:
    #     """상위 이슈 조회: 최신순 → 언론사 수 → 기사 수"""
    #     publisher_count = func.count(func.distinct(Article.publisher_id)).label("publisher_count")
    #     article_count = func.count(Article.id).label("article_count")
    #
    #     return (
    #         self.db.query(IssueLabel)
    #         .outerjoin(Article, Article.issue_label_id == IssueLabel.id)
    #         .group_by(IssueLabel.id)
    #         .order_by(
    #             desc(IssueLabel.created_at), # 1순위: 최신 이슈 우선
    #             desc(publisher_count),       # 2순위: 참여 언론사 수
    #             desc(article_count),         # 3순위: 기사 수
    #         )
    #         .limit(limit)
    #         .all()
    #     )

    def get_feed_issues(self, total: int = 30) -> List[IssueLabel]:
        """피드용 랭킹: 최신순 → 언론사 수 → 기사 수 순으로 정렬하여 N개 조회"""
        publisher_count = func.count(func.distinct(Article.publisher_id)).label("publisher_count")
        article_count = func.count(Article.id).label("article_count")

        return (
            self.db.query(IssueLabel)
            .outerjoin(Article, Article.issue_label_id == IssueLabel.id)
            .group_by(IssueLabel.id)
            .order_by(
                desc(IssueLabel.created_at), # 1순위: 최신 이슈 우선
                desc(publisher_count),       # 2순위: 참여 언론사 수
                desc(article_count),         # 3순위: 기사 수
            )
            .limit(total)
            .all()
        )

    # def get_by_id(self, issue_id: int) -> IssueLabel:
    #     """ID로 이슈 상세 조회"""
    #     return self.db.query(IssueLabel).filter(IssueLabel.id == issue_id).first()

    # def get_articles_with_publisher(self, issue_id: int) -> List[Article]:
    #     """특정 이슈에 속한 기사들을 언론사 정보와 함께 조회"""
    #     return self.db.query(Article)\
    #         .join(Publisher)\
    #         .filter(Article.issue_label_id == issue_id)\
    #         .all()

    def get_image_urls_by_issue(self, issue_id: int) -> List[str]:
        """이슈에 속한 모든 기사의 image_urls를 합산하여 반환"""
        articles = (
            self.db.query(Article.image_urls)
            .filter(
                Article.issue_label_id == issue_id,
                Article.image_urls.isnot(None),
            )
            .all()
        )
        result = []
        for (urls,) in articles:
            if urls:
                result.extend(urls)
        return result


    # def get_claims_by_issue(self, issue_id: int):
    #     """특정 이슈에 속한 모든 주장 카드 조회"""
    #     from app.domains.articles.models import ArticleClaim
    #     return self.db.query(ArticleClaim)\
    #         .filter(ArticleClaim.issue_id == issue_id)\
    #         .all()
