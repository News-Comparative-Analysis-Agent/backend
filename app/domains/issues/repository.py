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

    def get_today_stats(self, target_date: Optional[date] = None) -> dict:
        """
        주어진 날짜(기본값: 오늘)의 4대 핵심 통계를 반환합니다.
        (수집 기사 수, 생성 이슈 수, 참여 언론사 수, 비평 기사 생성 수)
        """
        if target_date:
            dt_date = target_date
        else:
            dt_date = (datetime.utcnow() + timedelta(hours=9)).date()
            
        today_start = datetime.combine(dt_date, datetime.min.time())
        today_end = datetime.combine(dt_date, datetime.max.time())
        
        # 1. 수집 기사 수
        article_count = self.db.query(func.count(Article.id)).filter(
            Article.published_at >= today_start,
            Article.published_at <= today_end
        ).scalar() or 0
        
        # 2. 생성 이슈 수
        issue_count = self.db.query(func.count(IssueLabel.id)).filter(
            IssueLabel.created_at >= today_start,
            IssueLabel.created_at <= today_end
        ).scalar() or 0

        # 3. 참여 언론사 수 (해당 날짜 기사가 있는 언론사 유니크 카운트)
        publisher_count = self.db.query(func.count(func.distinct(Article.publisher_id))).filter(
            Article.published_at >= today_start,
            Article.published_at <= today_end
        ).scalar() or 0

        # 4. 비평 기사 생성 수 (해당 날짜에 초안이 생성된 이슈 수)
        critique_count = self.db.query(func.count(IssueLabel.id)).filter(
            IssueLabel.created_at >= today_start,
            IssueLabel.created_at <= today_end,
            IssueLabel.pre_generated_draft.isnot(None),
            IssueLabel.pre_generated_draft != ""
        ).scalar() or 0
        
        return {
            "article_count": article_count,
            "issue_count": issue_count,
            "publisher_count": publisher_count,
            "critique_count": critique_count
        }

    def get_latest_daily_stats(self, target_date: date) -> Optional[IssueLabel]: # 실제로는 DailyStats 모델 반환
        from app.domains.issues.models import DailyStats
        return self.db.query(DailyStats).filter(cast(DailyStats.target_date, Date) == target_date).first()

    def sync_daily_stats(self, target_date: date) -> Optional[IssueLabel]:
        """당일 통계를 집계하여 daily_stats 테이블에 동기화합니다."""
        from app.domains.issues.models import DailyStats
        stats_data = self.get_today_stats(target_date)
        
        stats = self.get_latest_daily_stats(target_date)
        if stats:
            stats.article_count = stats_data["article_count"]
            stats.issue_count = stats_data["issue_count"]
            stats.publisher_count = stats_data["publisher_count"]
            stats.critique_count = stats_data["critique_count"]
            stats.last_updated_at = func.now()
        else:
            dt_start = datetime.combine(target_date, datetime.min.time())
            stats = DailyStats(
                target_date=dt_start,
                article_count=stats_data["article_count"],
                issue_count=stats_data["issue_count"],
                publisher_count=stats_data["publisher_count"],
                critique_count=stats_data["critique_count"]
            )
            self.db.add(stats)
        
        self.db.commit()
        self.db.refresh(stats)
        return stats

    def get_articles_for_issues(self, issue_ids: List[int]) -> dict:
        """
        이슈 ID 목록을 받아 각 이슈에 매핑된 전체 기사들의 제목과 언론사 이름을 반환합니다.
        """
        if not issue_ids:
            return {}
            
        articles = (
            self.db.query(Article, Publisher.name.label("publisher_name"))
            .join(Publisher, Article.publisher_id == Publisher.id)
            .filter(Article.issue_label_id.in_(issue_ids))
            .order_by(Article.published_at.desc())
            .all()
        )
        
        from collections import defaultdict
        result = defaultdict(list)
        seen_publishers = defaultdict(set)
        
        for art, pub_name in articles:
            if pub_name not in seen_publishers[art.issue_label_id]:
                result[art.issue_label_id].append({
                    "title": art.title,
                    "publisher": pub_name
                })
                seen_publishers[art.issue_label_id].add(pub_name)
            
        return dict(result)

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

    # =====================================================
    # 타임라인 관련 Repository 함수
    # =====================================================

    def get_recent_issues_for_linkage(self, days: int = None, exclude_id: int = None, limit: int = 20):
        query = self.db.query(IssueLabel).filter(IssueLabel.parent_issue_id == IssueLabel.id)
        
        if days is not None:
            cutoff = datetime.utcnow() - timedelta(days=days)
            query = query.filter(IssueLabel.created_at >= cutoff)
            
        if exclude_id:
            query = query.filter(IssueLabel.id != exclude_id)
            
        return query.order_by(IssueLabel.created_at.desc()).limit(limit).all()

    def update_issue_linkage(self, issue_id: int, parent_issue_id: int, phase: str):
        self.db.query(IssueLabel).filter(IssueLabel.id == issue_id).update({
            "parent_issue_id": parent_issue_id,
            "phase": phase
        })
        self.db.commit()

    def get_timeline_by_root(self, root_issue_id: int):
        return (
            self.db.query(IssueLabel)
            .filter(IssueLabel.parent_issue_id == root_issue_id)
            .order_by(IssueLabel.created_at.asc())
            .all()
        )

    def get_root_issue_id(self, issue_id: int) -> int:
        issue = self.db.query(IssueLabel).filter(IssueLabel.id == issue_id).first()
        if not issue:
            return issue_id
        if issue.parent_issue_id == issue.id:
            return issue.id
        return issue.parent_issue_id or issue.id

    def get_same_day_sibling(self, root_id: int, date_val: date, exclude_id: int) -> Optional[IssueLabel]:
        """같은 날, 같은 루트에 연결된 이슈 조회"""
        return (
            self.db.query(IssueLabel)
            .filter(
                IssueLabel.parent_issue_id == root_id,
                func.date(IssueLabel.created_at) == date_val,
                IssueLabel.id != exclude_id
            )
            .first()
        )

    def merge_into_existing(self, target_id: int, source_id: int):
        """source 이슈를 target에 흡수 (기사 수 합산, source 삭제)"""
        source = self.get_by_id(source_id)
        target = self.get_by_id(target_id)
        
        if not source or not target:
            return

        # 기사들 재연결
        self.db.query(Article).filter(
            Article.issue_label_id == source_id
        ).update({"issue_label_id": target_id})
        
        # 주장 카드(ArticleClaim) 재연결
        from app.domains.articles.models import ArticleClaim
        self.db.query(ArticleClaim).filter(
            ArticleClaim.issue_id == source_id
        ).update({"issue_id": target_id})
        
        # total_count 합산
        self.db.query(IssueLabel).filter(IssueLabel.id == target_id).update({
            "total_count": target.total_count + source.total_count
        })
        
        # source 이슈 삭제 (이미 조회된 객체가 있으므로 delete 호출)
        self.db.delete(source)
        self.db.commit()
