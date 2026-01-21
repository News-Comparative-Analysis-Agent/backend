from sqlalchemy import Column, Integer, String, Text, AppenderQuery, DateTime, func
from sqlalchemy.dialects.postgresql import ARRAY
from app.core.database import Base

class Topic(Base):
    """
    주제(Topic) 테이블
    - 뉴스 분석의 기준이 되는 정책이나 이슈를 관리합니다.
    - 예: '의대 증원', '연금 개혁' 등
    """
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False) # 주제명
    keywords = Column(ARRAY(Text)) # 주제와 관련된 키워드 리스트 (예: ["의대", "정원", "의사"])
    
    created_at = Column(DateTime, default=func.now()) # 생성 일시
