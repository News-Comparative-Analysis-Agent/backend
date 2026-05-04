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

    def get_feed_issues(self, target_date: Optional[date] = None, skip: int = 0, limit: int = 30, issue_type: Optional[str] = None) -> List[IssueLabel]:
        publisher_count = func.count(func.distinct(Article.publisher_id)).label("publisher_count")
        article_count = func.count(Article.id).label("article_count")

        query = (
            self.db.query(IssueLabel)
            .outerjoin(Article, Article.issue_label_id == IssueLabel.id)
        )

        if target_date:
            query = query.filter(cast(IssueLabel.created_at, Date) == target_date)

        if issue_type:
            query = query.filter(IssueLabel.issue_type == issue_type)

        return (
            query.group_by(IssueLabel.id)
            .order_by(
                desc(publisher_count),
                desc(article_count),
                desc(IssueLabel.created_at),
            )
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_feed_issues_count(self, target_date: Optional[date] = None, issue_type: Optional[str] = None) -> int:
        query = self.db.query(func.count(IssueLabel.id))

        if target_date:
            query = query.filter(cast(IssueLabel.created_at, Date) == target_date)

        if issue_type:
            query = query.filter(IssueLabel.issue_type == issue_type)

        return query.scalar() or 0

    def get_issues_by_date_range(self, days: int = 7, issue_type: Optional[str] = None) -> List[IssueLabel]:
        now_kst = datetime.utcnow() + timedelta(hours=9)
        cutoff_date = (now_kst - timedelta(days=days-1)).date()
        cutoff_dt = datetime.combine(cutoff_date, datetime.min.time())

        publisher_count = func.count(func.distinct(Article.publisher_id)).label("publisher_count")
        article_count = func.count(Article.id).label("article_count")

        query = (
            self.db.query(IssueLabel)
            .outerjoin(Article, Article.issue_label_id == IssueLabel.id)
            .filter(IssueLabel.created_at >= cutoff_dt)
        )

        if issue_type:
            query = query.filter(IssueLabel.issue_type == issue_type)

        return (
            query.group_by(IssueLabel.id)
            .order_by(
                desc(IssueLabel.created_at),
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

    def delete_issue(self, issue_id: int):
        """이슈 및 연관된 모든 데이터(기사, 본문, 주장 카드, 초안 참조) 연쇄 삭제"""
        from app.domains.articles.models import Article, ArticleBody, ArticleClaim
        from app.domains.drafts.models import DraftReference
        
        # 1. 연관된 기사 ID 조회 (튜플 형태 (id,)로 반환되므로 언패킹 필요)
        query_results = self.db.query(Article.id).filter(Article.issue_label_id == issue_id).all()
        article_ids = [r[0] for r in query_results]
        
        # 2. 연관된 주장 카드 삭제
        # 이슈 ID 기준 삭제
        self.db.query(ArticleClaim).filter(ArticleClaim.issue_id == issue_id).delete(synchronize_session=False)
        
        if article_ids:
            # 3. 기사 ID 기준으로 연관된 데이터들 삭제
            
            # 3-1. 주장 카드 (기사 ID 기준 - 이슈 ID가 불일치하는 경우 대비)
            self.db.query(ArticleClaim).filter(ArticleClaim.article_id.in_(article_ids)).delete(synchronize_session=False)
            
            # 3-2. 초안 참조(DraftReference) 삭제
            self.db.query(DraftReference).filter(DraftReference.article_id.in_(article_ids)).delete(synchronize_session=False)
            
            # 3-3. 기사 본문 삭제
            self.db.query(ArticleBody).filter(ArticleBody.article_id.in_(article_ids)).delete(synchronize_session=False)
            
            # 3-4. 기사 삭제
            self.db.query(Article).filter(Article.id.in_(article_ids)).delete(synchronize_session=False)
        
        # 4. 이슈 레이블 삭제
        issue = self.get_by_id(issue_id)
        if issue:
            self.db.delete(issue)
            
    def update_issue_analysis_results(self, issue_id: int, 
                                     description: str = None,
                                     background: str = None,
                                     conflict_summary: str = None):
        """이슈 레이블의 분석 결과 필드들을 부분 업데이트합니다."""
        issue = self.get_by_id(issue_id)
        if issue:
            if description is not None:
                issue.description = description
            if background is not None:
                issue.background = background
            if conflict_summary is not None:
                issue.conflict_summary = conflict_summary
            self.db.commit()
            return True
        return False
