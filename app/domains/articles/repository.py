from sqlalchemy import cast, Date
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import date, datetime, timedelta
from app.domains.articles.models import Article, ArticleClaim

class ArticleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_articles(self, issue_id: Optional[int] = None, target_date: Optional[date] = None, limit: int = 20) -> List[Article]:
        """기사 목록 조회 (최신순 + 필터링)"""
        query = self.db.query(Article).options(joinedload(Article.publisher))
        
        if issue_id:
            query = query.filter(Article.issue_label_id == issue_id)
        
        if target_date:
            query = query.filter(cast(Article.published_at, Date) == target_date)
            
        return query.order_by(Article.published_at.desc()).limit(limit).all()

    def get_articles_by_date_range(self, days: int = 7, limit_per_day: int = 50) -> List[Article]:
        """최근 N일간의 기사 조회"""
        # KST 기준 현재 시각에서 N일 전의 시작 시각 계산
        now_kst = datetime.utcnow() + timedelta(hours=9)
        cutoff_date = (now_kst - timedelta(days=days-1)).date()
        cutoff_dt = datetime.combine(cutoff_date, datetime.min.time())

        return (
            self.db.query(Article)
            .options(joinedload(Article.publisher))
            .filter(Article.published_at >= cutoff_dt)
            .order_by(Article.published_at.desc())
            .limit(days * limit_per_day)
            .all()
        )

    def get_article(self, article_id: int) -> Optional[Article]:
        """기사 상세 조회"""
        return self.db.query(Article).options(joinedload(Article.publisher)).filter(Article.id == article_id).first()

    def get_articles_by_issue(self, issue_label_id: int, limit: int = 20) -> List[Article]:
        """이슈 라벨(클러스터)별 기사 목록 조회"""
        return self.db.query(Article).filter(
            Article.issue_label_id == issue_label_id
        ).order_by(Article.published_at.desc()).limit(limit).all()

    def get_publishers_by_names(self, names: List[str]):
        """언론사명 리스트로 언론사 목록 조회"""
        from app.domains.publishers.models import Publisher
        return self.db.query(Publisher).filter(Publisher.name.in_(names)).all()

    def save_article_claim(self, issue_id: int, article_id: int, press: str, claim: str, evidence_front: str = None, evidence_back: str = None, issue_type: str = "editorial", **kwargs) -> ArticleClaim:
        """에이전트 1이 추출한 주장 데이터를 저장합니다 (기존 데이터가 있으면 덮어씌움)."""
        # 하위 호환성: 옛날 코드에서 'evidence' 키워드로 전달했을 경우 대응
        if evidence_front is None and "evidence" in kwargs:
            evidence_front = kwargs["evidence"]

        # DB 컬럼 호환성을 위해 두 영역을 합쳐서 저장
        if issue_type == "politics":
            combined_evidence = f"[사건·팩트]\n{evidence_front or ''}\n\n[반응·입장]\n{evidence_back or ''}".strip()
        else:
            combined_evidence = f"[판단·해석]\n{evidence_front or ''}\n\n[결론·요구]\n{evidence_back or ''}".strip()
        
        # 기존 데이터 존재 여부 확인 (issue_id와 article_id 쌍으로 검색)
        db_claim = self.db.query(ArticleClaim).filter(
            ArticleClaim.issue_id == issue_id,
            ArticleClaim.article_id == article_id
        ).first()

        if db_claim:
            # 기존 데이터가 있으면 필드 업데이트 (덮어씌우기)
            db_claim.press = press
            db_claim.claim = claim
            db_claim.evidence = combined_evidence
        else:
            # 없으면 새 객체 생성
            db_claim = ArticleClaim(
                issue_id=issue_id,
                article_id=article_id,
                press=press,
                claim=claim,
                evidence=combined_evidence
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