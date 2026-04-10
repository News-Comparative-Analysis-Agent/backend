from sqlalchemy.orm import Session
from sqlalchemy import func, desc, cast, Date
from typing import List, Optional
from app.domains.issues.models import IssueLabel
from app.domains.articles.models import Article
from app.domains.publishers.models import Publisher

from datetime import datetime, date, timedelta

class IssueRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_recent_issues_for_timeline(self, limit: int = 500) -> List[IssueLabel]:
        """최근 이슈들을 가져와서 타임라인/유사도 분석의 후보군으로 사용"""
        return (
            self.db.query(IssueLabel)
            .order_by(IssueLabel.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_feed_issues(self, target_date: Optional[date] = None, total: int = 30) -> List[IssueLabel]:
        """피드용 랭킹: (날짜필터) → 언론사 수 → 기사 수 순으로 정렬하여 N개 조회"""
        publisher_count = func.count(func.distinct(Article.publisher_id)).label("publisher_count")
        article_count = func.count(Article.id).label("article_count")

        query = (
            self.db.query(IssueLabel)
            .outerjoin(Article, Article.issue_label_id == IssueLabel.id)
        )

        if target_date:
            # PostgreSQL/SQLite 모두에서 동작하도록 cast 사용 (created_at은 DateTime)
            query = query.filter(cast(IssueLabel.created_at, Date) == target_date)

        return (
            query.group_by(IssueLabel.id)
            .order_by(
                desc(publisher_count),       # 1순위: 참여 언론사 수
                desc(article_count),         # 2순위: 기사 수
                desc(IssueLabel.created_at), # 3순위: 생성 시각
            )
            .limit(total)
            .all()
        )

    def get_issues_by_date_range(self, days: int = 7) -> List[IssueLabel]:
        """최근 N일간의 이슈 조회"""
        # KST 기준 현재 시각에서 N일 전의 시작 시각 계산
        now_kst = datetime.utcnow() + timedelta(hours=9)
        cutoff_date = (now_kst - timedelta(days=days-1)).date()
        cutoff_dt = datetime.combine(cutoff_date, datetime.min.time())

        publisher_count = func.count(func.distinct(Article.publisher_id)).label("publisher_count")
        article_count = func.count(Article.id).label("article_count")

        return (
            self.db.query(IssueLabel)
            .outerjoin(Article, Article.issue_label_id == IssueLabel.id)
            .filter(IssueLabel.created_at >= cutoff_dt)
            .group_by(IssueLabel.id)
            .order_by(
                desc(IssueLabel.created_at), # 시간순 정렬 (그룹화 용이)
                desc(publisher_count),
                desc(article_count),
            )
            .all()
        )

    def get_by_id(self, issue_id: int) -> IssueLabel:
        """ID로 이슈 상세 조회"""
        return self.db.query(IssueLabel).filter(IssueLabel.id == issue_id).first()

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

    def get_image_urls_by_issue_ids(self, issue_ids: List[int]) -> dict:
        """여러 이슈에 속한 기사들의 image_urls를 합산하여 딕셔너리로 반환 (이슈ID -> 이미지 URL 리스트)"""
        if not issue_ids:
            return {}
        
        articles = (
            self.db.query(Article.issue_label_id, Article.image_urls)
            .filter(
                Article.issue_label_id.in_(issue_ids),
                Article.image_urls.isnot(None),
            )
            .all()
        )
        
        from collections import defaultdict
        result = defaultdict(list)
        for issue_id, urls in articles:
            if urls:
                result[issue_id].extend(urls)
        return dict(result)

    def get_claims_by_issue(self, issue_id: int):
        """특정 이슈에 속한 모든 주장 카드 조회"""
        from app.domains.articles.models import ArticleClaim
        return self.db.query(ArticleClaim)\
            .filter(ArticleClaim.issue_id == issue_id)\
            .all()
