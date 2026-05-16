# app/scroller/repository.py
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text
from datetime import datetime, timedelta
import pytz
from app.domains.articles.models import Article, ArticleBody, ArticleClaim
from app.domains.publishers.models import Publisher
from app.domains.issues.models import IssueLabel
from app.domains.drafts.models import DraftReference
from app.domains.users.models import User
from app.domains.system.models import SystemSettings
from app.core.logger import logger

class ScrollerRepository:
    """
    스크롤러 패키지 전용 데이터 저장소 클래스
    SQLAlchemy를 사용하여 DB CRUD(생성, 조회, 수정, 삭제)를 담당합니다.
    """
    
    def __init__(self, db: Session):
        """
        Args:
            db (Session): 외부에서 주입받은 SQLAlchemy DB 세션
        """
        self.db = db

    def delete_old_articles(self, days: int = 30) -> int:
        """
        설정된 기간보다 오래된 기사 데이터를 삭제합니다.
        기사 본문(ArticleBody)이 외래키로 연결되어 있으므로 먼저 삭제합니다.
        
        Args:
            days (int): 기준 기간 (30일)
            
        Returns:
            int: 삭제된 기사의 총 개수
        """
        KST = pytz.timezone('Asia/Seoul')
        kst_now = datetime.now(pytz.utc).astimezone(KST).replace(tzinfo=None)
        cutoff_date = kst_now - timedelta(days=days)
        # 특정 기간 이전의 기사 조회
        old_articles = self.db.query(Article).filter(Article.published_at < cutoff_date).all()
        old_article_ids = [a.id for a in old_articles]
        
        deleted_count = 0
        if old_article_ids:
            # 1. 연결된 데이터 선삭제 (외래키 제약 조건 준수)
            self.db.query(ArticleBody).filter(ArticleBody.article_id.in_(old_article_ids)).delete(synchronize_session=False)
            self.db.query(ArticleClaim).filter(ArticleClaim.article_id.in_(old_article_ids)).delete(synchronize_session=False)
            self.db.query(DraftReference).filter(DraftReference.article_id.in_(old_article_ids)).delete(synchronize_session=False)
            
            # 2. 기사 메타데이터 삭제
            deleted_count = self.db.query(Article).filter(Article.id.in_(old_article_ids)).delete(synchronize_session=False)
            self.db.flush() # 변경사항 즉시 반영 (Commit 전)
            
        return deleted_count


    def get_or_create_publisher(self, press_name: str) -> Publisher:
        """
        언론사 정보를 조회하고, 없으면 새로 생성하여 반환합니다.
        
        Args:
            press_name (str): 언론사 이름 (예: '한겨레')
            
        Returns:
            Publisher: 조회되거나 새로 생성된 언론사 객체
        """
        publisher = self.db.query(Publisher).filter(Publisher.name == press_name).first()
        if not publisher:
            # 내부 코드가 없는 경우 이름을 코드로 임시 할당
            publisher = Publisher(name=press_name, code=press_name)
            self.db.add(publisher)
            self.db.flush()
        return publisher

    def is_article_exists(self, url: str) -> bool:
        """
        기사가 이미 DB에 존재하는지 URL을 기준으로 확인합니다 (중복 수집 방지).
        
        Args:
            url (str): 기사 원문 URL
            
        Returns:
            bool: 존재 여부
        """
        existing = self.db.query(Article).filter(Article.url == url).first()
        return existing is not None

    def save_article_with_body(self, publisher_id: int, 
                                title: str, url: str, image_urls: list,
                                 published_at: datetime, content: str,
                                 reporter: str = None, article_type: str = "editorial") -> Article:
        """
        기사 메타데이터와 본문을 각각의 테이블에 연동하여 저장합니다.
        
        Args:
            publisher_id (int): 소속 언론사 ID
            title (str): 기사 제목
            url (str): 기사 링크
            image_urls (list): 이미지 URL 리스트
            published_at (datetime): 발행 일시
            content (str): 기사 원문 (본문)
            reporter (str): 기자 이름
            article_type (str): 기사 유형 (editorial/politics)
            
        Returns:
            Article: 저장된 기사 객체
        """
        # 1. 기사 메타데이터 객체 생성 및 추가
        article = Article(
            publisher_id=publisher_id,
            title=title,
            url=url,
            image_urls=image_urls,
            published_at=published_at,
            reporter=reporter,
            article_type=article_type
        )
        self.db.add(article)
        self.db.flush() # article.id를 획득하기 위해 flush 수행

        # 2. 본문(Body) 데이터 연동 저장
        body = ArticleBody(
            article_id=article.id,
            raw_content=content
        )
        self.db.add(body)
        return article

    def get_unclustered_articles(self, article_type: str = "editorial") -> list[Article]:
        """
        이슈 라벨이 아직 할당되지 않은(None) 기사 리스트를 조회합니다.
        지정된 article_type(editorial 또는 politics)에 해당하는 기사만 가져옵니다.
        클러스터링 파이프라인의 시작 데이터로 사용됩니다.
        """
        return self.db.query(Article).filter(Article.issue_label_id == None, Article.article_type == article_type).all()
        
    def search_articles_by_keyword(self, keyword: str, limit: int = 15) -> list[Article]:
        """
        키워드를 포함한 기사를 제목 및 본문에서 검색합니다.
        
        Args:
            keyword (str): 검색어
            limit (int): 최대 결과 수
            
        Returns:
            list[Article]: 최신순으로 정렬된 기사 리스트
        """
        search_pattern = f"%{keyword}%"
        
        # 조인 및 필터 조건을 명확하게 분리하여 쿼리 구성
        query = (
            self.db.query(Article)
            .outerjoin(ArticleBody)
            .filter(
                Article.title.ilike(search_pattern) | 
                ArticleBody.raw_content.ilike(search_pattern)
            )
            .order_by(Article.published_at.desc())
            .limit(limit)
        )
        
        return query.all()

    def search_issues_by_keyword(self, keyword: str, limit: int = 20) -> list:
        """
        검색어를 공백으로 분리한 토큰 단위로 이슈를 OR 검색합니다.
        각 토큰이 name / description / background / conflict_summary 중
        하나라도 포함된 이슈를 최신순으로 반환합니다.

        예) "이재명 탄핵" → '이재명' OR '탄핵' 포함 이슈 모두 반환

        Args:
            keyword (str): 검색어 (자연어 문장 가능)
            limit (int): 최대 결과 수
        """
        from sqlalchemy import or_

        # 2글자 이상 토큰만 사용 (조사·단어 노이즈 방지)
        tokens = [t for t in keyword.split() if len(t) >= 2]

        # 토큰이 없으면 전체 검색어를 그대로 사용
        if not tokens:
            tokens = [keyword]

        conditions = []
        for token in tokens:
            pattern = f"%{token}%"
            conditions.append(IssueLabel.name.ilike(pattern))
            conditions.append(IssueLabel.description.ilike(pattern))
            conditions.append(IssueLabel.background.ilike(pattern))
            conditions.append(IssueLabel.conflict_summary.ilike(pattern))

        return (
            self.db.query(IssueLabel)
            .filter(or_(*conditions))
            .order_by(IssueLabel.created_at.desc())
            .limit(limit)
            .all()
        )

    def save_issue_and_relations(self, ai_label: str, 
                                    description: str, 
                                    count: int, 
                                    article_ids_to_update: list, 
                                    background: str = None,
                                    issue_type: str = "editorial") -> IssueLabel:
        """
        AI가 식별한 새로운 이슈(토픽)를 생성하고, 관련 기사들을 이 이슈에 매핑합니다.
        
        Args:
            ai_label (str): AI가 명명한 이슈 제목
            description (str): 이슈 요약 설명
            count (int): 포함된 기사 수
            article_ids_to_update (list): 이 이슈에 소속될 기사 ID 리스트
            background (str): 이슈 배경 상세
            issue_type (str): 이슈 유형 (editorial/politics)
            
        Returns:
            IssueLabel: 생성된 이슈 객체
        """
        # 1. 이슈 레이블 생성
        issue = IssueLabel(
            name=ai_label,
            description=description,
            total_count=int(count),
            background=background,
            issue_type=issue_type,
            created_at=datetime.now(pytz.utc).astimezone(pytz.timezone('Asia/Seoul')).replace(tzinfo=None) # KST 강제 적용
        )
        self.db.add(issue)
        self.db.flush() 

        # 2. 연관된 기사들의 issue_label_id를 일괄 업데이트
        update_query = (
            self.db.query(Article)
            .filter(Article.id.in_(article_ids_to_update))
        )
        update_query.update({"issue_label_id": issue.id}, synchronize_session=False)
        
        return issue
        
    def delete_issue_by_id(self, issue_id: int):
        """
        특정 이슈를 삭제하고 소속 기사들의 연관관계를 해제하며, 
        연관된 클레임 카드들을 정리합니다.
        """
        # 1. 소속 기사들의 관계 해제 (Article 테이블)
        self.db.query(Article).filter(Article.issue_label_id == issue_id).update({"issue_label_id": None}, synchronize_session=False)
        
        # 2. 연관된 클레임 카드 삭제
        self.db.query(ArticleClaim).filter(ArticleClaim.issue_id == issue_id).delete(synchronize_session=False)
        
        # 3. 이슈 삭제
        self.db.query(IssueLabel).filter(IssueLabel.id == issue_id).delete(synchronize_session=False)
        
        self.db.flush()
        logger.info(f"🗑️ [ScrollerRepository] 이슈 ID {issue_id} 및 연관 데이터(Claims) 삭제 완료.")

    def get_issue_by_id(self, issue_id: int) -> IssueLabel:
        """
        이슈 ID로 이슈 상세 정보를 조회합니다.
        """
        return self.db.query(IssueLabel).filter(IssueLabel.id == issue_id).first()

    def get_articles_by_issue(self, issue_id: int) -> list[Article]:
        """
        특정 이슈에 속한 모든 기사와 본문, 언론사 정보를 한꺼번에 가져옵니다.
        """
        return (
            self.db.query(Article)
            .options(joinedload(Article.body), joinedload(Article.publisher))
            .filter(Article.issue_label_id == issue_id)
            .all()
        )

    def truncate_all_data(self):
        """
        데이터베이스의 기사 및 이슈 데이터를 완전히 삭제하고 PK 시퀀스를 초기화합니다.
        (테스트 및 리셋용)
        """
        # CASCADE 옵션을 통해 연관된 데이터까지 모두 삭제
        self.db.execute(text("TRUNCATE TABLE issue_labels, articles RESTART IDENTITY CASCADE"))


    def update_system_llm_mode(self, mode: str) -> SystemSettings:
        """
        시스템 전역 LLM 모드를 업데이트합니다.
        id=1인 레코드를 업데이트하며, 없으면 생성합니다.
        """
        settings = self.db.query(SystemSettings).filter(SystemSettings.id == 1).first()
        if not settings:
            settings = SystemSettings(id=1, llm_mode=mode)
            self.db.add(settings)
        else:
            settings.llm_mode = mode
        
        self.db.flush()
        return settings

    def get_system_settings(self) -> SystemSettings:
        """
        시스템 설정을 조회합니다. 없으면 기본값으로 생성합니다.
        """
        settings = self.db.query(SystemSettings).filter(SystemSettings.id == 1).first()
        if not settings:
            # 기본 설정 생성
            settings = SystemSettings(id=1, llm_mode="gemini_only")
            self.db.add(settings)
            self.db.flush()
        return settings

    def update_issue_draft(self, issue_id: int, draft_text: str):
        """
        이슈 레이블의 pre_generated_draft 컬럼을 업데이트합니다.
        """
        issue = self.db.query(IssueLabel).filter(IssueLabel.id == issue_id).first()
        if issue:
            issue.pre_generated_draft = draft_text
            self.db.flush()
            logger.info(f"✅ [ScrollerRepository] 이슈 ID {issue_id}에 초안 저장 완료 (길이: {len(draft_text)}). flush() 호출됨.")
            return True
        logger.error(f"❌ [ScrollerRepository] 이슈 ID {issue_id}를 찾을 수 없어 초안을 저장하지 못했습니다.")
        return False

    

    def update_issue_analysis_results(self, issue_id: int, 
                                     description: str = None,
                                     background: str = None,
                                     conflict_summary: str = None,
                                     status: str = None):
        """
        이슈 레이블의 분석 결과 필드들을 부분 업데이트합니다.
        """
        issue = self.db.query(IssueLabel).filter(IssueLabel.id == issue_id).first()
        if issue:
            if description is not None:
                issue.description = description
            if background is not None:
                issue.background = background
            if conflict_summary is not None:
                issue.conflict_summary = conflict_summary
            if status is not None:
                issue.status = status
            self.db.flush()
            return True
        return False

    def update_issue_status(self, issue_id: int, status: str):
        """
        이슈의 상태(analyzing, success, failed)를 업데이트합니다.
        """
        issue = self.db.query(IssueLabel).filter(IssueLabel.id == issue_id).first()
        if issue:
            issue.status = status
            self.db.flush()
            return True
        return False

    # =====================================================
    # 타임라인 관련 Repository 함수
    # =====================================================

    def get_recent_issues_for_linkage(self, days: int = None, exclude_id: int = None):
        """
        최근 N일 이내 또는 전체 이슈 조회 (후속 판별 후보군)
        - exclude_id: 새로 생성된 이슈 자신은 제외
        - parent_issue_id = 자기 자신인 것만 (루트 이슈들만 비교)
        """
        from app.domains.issues.models import IssueLabel
        
        query = self.db.query(IssueLabel).filter(IssueLabel.parent_issue_id == IssueLabel.id)
        
        if days is not None:
            cutoff = datetime.utcnow() - timedelta(days=days)
            query = query.filter(IssueLabel.created_at >= cutoff)
        
        if exclude_id:
            query = query.filter(IssueLabel.id != exclude_id)
        
        return query.order_by(IssueLabel.created_at.desc()).all()

    def update_issue_linkage(self, issue_id: int, parent_issue_id: int, phase: str):
        """
        이슈의 parent_issue_id와 phase 업데이트
        기존 이슈는 절대 건드리지 않고, 해당 issue_id만 업데이트
        """
        from app.domains.issues.models import IssueLabel
        
        self.db.query(IssueLabel).filter(IssueLabel.id == issue_id).update({
            "parent_issue_id": parent_issue_id,
            "phase": phase
        })
        self.db.commit()

    def get_timeline_by_root(self, root_issue_id: int):
        """
        root_issue_id 기준으로 전체 타임라인 조회
        parent_issue_id = root_issue_id 인 것들 + 루트 자신
        시간순(과거→최신) 정렬
        """
        from app.domains.issues.models import IssueLabel
        
        return (
            self.db.query(IssueLabel)
            .filter(IssueLabel.parent_issue_id == root_issue_id)
            .order_by(IssueLabel.created_at.asc())
            .all()
        )

    def get_root_issue_id(self, issue_id: int) -> int:
        """
        주어진 issue_id의 루트 이슈 ID 반환
        parent_issue_id == id 인 것이 루트
        """
        from app.domains.issues.models import IssueLabel
        
        issue = self.db.query(IssueLabel).filter(IssueLabel.id == issue_id).first()
        if not issue:
            return issue_id
        
        # parent가 자기 자신이면 루트
        if issue.parent_issue_id == issue.id:
            return issue.id
        
        # 아니면 parent의 루트를 재귀 탐색 (최대 1단계 - 구조상 2depth 이상 없음)
        return issue.parent_issue_id or issue.id
