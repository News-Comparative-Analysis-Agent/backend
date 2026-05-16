from sqlalchemy import Column, Integer, String, Text, DateTime, func, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import ARRAY
from app.core.database import Base

class IssueLabel(Base):
    """
    이슈 레이블(Issue Label) 테이블
    - 기사들을 군집화(Clustering)하여 생성된 구체적인 '이슈/사건' 데이터입니다.
    - 예: '의대 증원 갈등 심화', '전공의 집단 사직' 등
    """
    __tablename__ = "issue_labels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False) # 이슈명 (예: 전공의 집단 사직)
    description = Column(Text) # 이슈 배경 설명
    issue_type = Column(String, nullable=False, default="editorial", server_default="editorial") # 이슈 유형 (editorial 또는 politics)
    
    # 타임라인/상태 추적 필드
    status = Column(String(20), default="analyzing", server_default="analyzing", index=True) # analyzing, success, failed
    parent_issue_id = Column(Integer, ForeignKey("issue_labels.id", ondelete="SET NULL"), nullable=True)
    phase = Column(String(10), default="발생", server_default="발생")
    
    # ORM에서 부모-자식 관계를 편하게 탐색하기 위한 Self-referencing 설정
    parent = relationship("IssueLabel", remote_side=[id], backref="children", post_update=True)
    
    # 추가 필드 (Repository에서 사용 중)
    background = Column(Text, nullable=True) # 이슈의 배경 정보
    conflict_summary = Column(Text, nullable=True) # 갈등 요약
    
    total_count = Column(Integer, default=0) # 해당 이슈에 속한 기사 수
    pre_generated_draft = Column(Text, nullable=True) # AI가 미리 생성한 초안 텍스트 (명령어에 따라 백그라운드에서 캐싱됨)
    created_at = Column(DateTime, default=func.now(), index=True) # 생성 일시

    articles = relationship("Article", back_populates="issue_label")

class DailyStats(Base):
    """
    당일 서비스 통계 정보 테이블
    - 대시보드 상단에 표시될 요약 수치들을 저장합니다.
    """
    __tablename__ = "daily_stats"

    id = Column(Integer, primary_key=True, index=True)
    target_date = Column(DateTime, unique=True, index=True) # 집계 대상 날짜 (시간 제외)
    article_count = Column(Integer, default=0) # 오늘 수집된 총 기사 수
    issue_count = Column(Integer, default=0)   # 오늘 생성된 총 이슈 수
    publisher_count = Column(Integer, default=0) # 참여 언론사 수 (기사 소속 기준)
    critique_count = Column(Integer, default=0)  # 오늘 생성된 비평/초안 기사 수
    last_updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
