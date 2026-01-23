from sqlalchemy import Column, Integer, String, Date, Float, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base

class KeywordRelation(Base):
    """
    키워드 관계(Keyword Network) 테이블
    - 특정 이슈(IssueLabel) 내에서 두 키워드가 기사에서 동시 출현(Co-occurrence)한 빈도를 저장합니다.
    - 네트워크 그래프 시각화에 사용됩니다.
    """
    __tablename__ = "keyword_relations"

    date = Column(Date, primary_key=True)
    
    issue_label_id = Column(Integer, ForeignKey("issue_labels.id"), primary_key=True)
    keyword_a = Column(String, primary_key=True) # 키워드 A
    keyword_b = Column(String, primary_key=True) # 키워드 B
    
    frequency = Column(Integer, default=0) # 동시 출현 빈도

    # 관계 설정
    issue_label = relationship("IssueLabel", back_populates="keyword_relations")
