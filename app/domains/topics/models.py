from sqlalchemy import Column, Integer, String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from app.core.database import Base

class Topic(Base):
    """
    주제(Topic) 테이블
    - 뉴스 분석의 기준이 되는 정책이나 이슈를 관리합니다.
    - 예: '의대 증원', '연금 개혁' 등
    """
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False) # 주제명 예: ["의대정원"]
    keywords = Column(ARRAY(Text)) # 주제와 관련된 키워드 리스트 (예: ["의대", "정원", "의사"])
    graph_data = Column(JSONB) # 키워드 관계망 데이터 (e.g. {nodes: [], links: []})
    
    created_at = Column(DateTime, default=func.now()) # 생성 일시
