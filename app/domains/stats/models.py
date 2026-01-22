from sqlalchemy import Column, Integer, String, Date, Float, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base

class DailyTopicStats(Base):
    """
    일별 주제 통계(Daily Stats) 테이블
    - 대시보드 성능을 위해 매일 밤 집계된 통계 데이터를 저장합니다.
    """
    __tablename__ = "daily_topic_stats"

    date = Column(Date, primary_key=True) # 날짜 (YYYY-MM-DD)
    topic_id = Column(Integer, ForeignKey("topics.id"), primary_key=True)
    
    article_count = Column(Integer, default=0) # 해당 일자 기사 수
    bias_distribution = Column(JSONB) # 성향 분포 (예: {"neutral": 60, "conservative": 20})
    top_keywords = Column(JSONB) # 상위 키워드 (예: {"의사": 50, "파업": 30})

    # 관계 설정
    topic = relationship("Topic")

class KeywordRelation(Base):
    """
    키워드 관계(Keyword Network) 테이블
    - 두 키워드가 기사에서 동시 출현(Co-occurrence)한 빈도를 저장합니다.
    - 네트워크 그래프 시각화에 사용됩니다.
    """
    __tablename__ = "keyword_relations"

    date = Column(Date, primary_key=True)
    
    topic_id = Column(Integer, ForeignKey("topics.id"), primary_key=True)
    keyword_a = Column(String, primary_key=True) # 키워드 A
    keyword_b = Column(String, primary_key=True) # 키워드 B
    
    frequency = Column(Integer, default=0) # 동시 출현 빈도

    # 관계 설정
    topic = relationship("Topic")
