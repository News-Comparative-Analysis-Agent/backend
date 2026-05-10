from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, func, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from app.core.database import Base

# 외래키 관계(relationship)를 위해 모델 명시적 임포트
from app.domains.issues.models import IssueLabel 
from app.domains.publishers.models import Publisher

class Article(Base):
    """
    기사(Article) 테이블
    - 수집된 뉴스의 메타데이터와 AI 분석 결과를 저장합니다.
    """
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    issue_label_id = Column(Integer, ForeignKey("issue_labels.id"), nullable=True, index=True) # 소속 이슈 (클러스터링 결과)
    publisher_id = Column(Integer, ForeignKey("publishers.id")) # 언론사 ID
    article_type = Column(String, nullable=False, default="editorial", server_default="editorial") # 기사 유형 (editorial 또는 politics)
    
    title = Column(String, nullable=False) # 기사 제목
    url = Column(String, unique=True, nullable=False) # 기사 원문 URL
    image_urls = Column(ARRAY(Text)) # 기사 내 이미지 URL 리스트
    
    published_at = Column(DateTime, nullable=False) # 기사 발행 일시
    reporter = Column(String, nullable=True) # 기자 이름
    
    
    # AI 분석 결과 데이터
    analyzed_at = Column(DateTime, default=func.now()) # 분석 완료 일시

    # 관계 설정
    issue_label = relationship("IssueLabel", back_populates="articles")
    publisher = relationship("Publisher", back_populates="articles")
    body = relationship("ArticleBody", uselist=False, back_populates="article") # 1:1 관계

class ArticleBody(Base):
    """
    기사 본문(Body) 테이블
    - 기사의 원문 텍스트를 저장합니다. 별도 테이블로 분리.
    """
    __tablename__ = "article_body"

    article_id = Column(Integer, ForeignKey("articles.id"), primary_key=True)
    raw_content = Column(Text) # 본문 전체 텍스트


    # 관계 설정
    article = relationship("Article", back_populates="body")


class ArticleClaim(Base):
    __tablename__ = "article_claim_card"
    id = Column(Integer, primary_key=True, index=True)
    issue_id = Column(Integer, ForeignKey("issue_labels.id"), index=True)
    article_id = Column(Integer, ForeignKey("articles.id"))

    press = Column(String, nullable=False)   # 언론사
    claim = Column(Text, nullable=False)    # 핵심 주장
    evidence = Column(Text)                 # 근거 문장
    
    # 관계 설정
    issue = relationship("IssueLabel")
    article = relationship("Article")