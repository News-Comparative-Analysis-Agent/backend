from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func, Float
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import ARRAY
from app.core.database import Base

class Draft(Base):
    """
    초안(Draft) 테이블
    - 사용자가 작성 중인 기사 초안을 저장합니다.
    """
    __tablename__ = "drafts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id")) # 작성자 ID
    
    title = Column(String) # 초안 제목
    content = Column(Text) # 작성 중인 본문 내용
    image_urls = Column(ARRAY(Text)) # 삽입된 이미지들
    
    generated_perspective = Column(String) # AI가 사용한 논점
    status = Column(String, default="draft") # 상태 (draft: 작성중, completed: 완료, published: 발행)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # 관계 설정
    user = relationship("User", backref="drafts")
    references = relationship("DraftReference", back_populates="draft")

class DraftReference(Base):
    """
    참조 기사(Draft Reference) 테이블
    - 초안 작성 시 사용자가 참고(인용)한 기사들을 연결합니다. (Many-to-Many)
    """
    __tablename__ = "draft_references"

    draft_id = Column(Integer, ForeignKey("drafts.id"), primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), primary_key=True)
    
    similarity_score = Column(Float) # 주제 유사도 (선택적)

    # 관계 설정
    draft = relationship("Draft", back_populates="references")
    article = relationship("Article")
