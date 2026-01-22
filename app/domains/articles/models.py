from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, func, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from app.core.database import Base

class Article(Base):
    """
    기사(Article) 테이블
    - 수집된 뉴스의 메타데이터와 AI 분석 결과를 저장합니다.
    """
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("topics.id")) # 관련 주제 ID
    publisher_id = Column(Integer, ForeignKey("publishers.id")) # 언론사 ID
    
    title = Column(String, nullable=False) # 기사 제목
    url = Column(String, unique=True, nullable=False) # 기사 원문 URL
    image_urls = Column(ARRAY(Text)) # 기사 내 이미지 URL 리스트
    
    published_at = Column(DateTime, nullable=False) # 기사 발행 일시
    
    
    # AI 분석 결과 데이터
    summary = Column(Text) # 3줄 요약
    bias = Column(String) # 정치 성향 (neutral, conservative, liberal)
    bias_score = Column(Float) # 성향 강도 (0.0 ~ 10.0)
    key_arguments = Column(JSONB) # 핵심 논점/키워드 리스트 (JSON)
    
    analyzed_at = Column(DateTime, default=func.now()) # 분석 완료 일시

    # 관계 설정
    topic = relationship("Topic", backref="articles")
    publisher = relationship("Publisher", backref="articles")
    body = relationship("ArticleBody", uselist=False, back_populates="article") # 1:1 관계

class ArticleBody(Base):
    """
    기사 본문(Body) 테이블
    - 기사의 원문 텍스트를 저장합니다. 별도 테이블로 분리.
    """
    __tablename__ = "article_body"

    article_id = Column(Integer, ForeignKey("articles.id"), primary_key=True)
    raw_content = Column(Text) # 본문 전체 텍스트
    collected_at = Column(DateTime, default=func.now()) # 수집 일시

    # 관계 설정
    article = relationship("Article", back_populates="body")
