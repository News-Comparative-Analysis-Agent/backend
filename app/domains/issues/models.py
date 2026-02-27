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
    total_count = Column(Integer, default=0) # 해당 이슈에 속한 기사 수
    background = Column(Text, nullable=True) # 핵심 발단/배경
    core_contentions = Column(Text, nullable=True) # 주요 쟁점
    media_ratio = Column(String, nullable=True) # 언론사 비율 추출 결과 (JSON 문자열 등)
    created_at = Column(DateTime, default=func.now()) # 생성 일시

    articles = relationship("Article", back_populates="issue_label")
