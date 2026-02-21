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
    
    # 수정: topics -> issue_labels
    issue_label_id = Column(Integer, ForeignKey("issue_labels.id")) # 관련 이슈(주제) ID
    
    title = Column(String) # 초안 제목
    content = Column(Text) # 작성 중인 본문 내용
    image_urls = Column(ARRAY(Text)) # 삽입된 이미지들
    
    status = Column(String, default="draft") # 상태 (draft: 작성중, completed: 완료, published: 발행)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # 관계 설정
    user = relationship("User", backref="drafts")
    
    # 수정: Topic -> IssueLabel
    # 문자열로 "IssueLabel"을 참조하되, 순환 참조 방지 등을 위해 'app.domains.issues.models.IssueLabel' 처럼 명시하거나
    # 단순히 "IssueLabel"로 쓰고 Base.metadata가 공유되는지 확인해야 함.
    # 여기서는 다른 파일들처럼 문자열 참조를 사용.
    issue_label = relationship("IssueLabel", backref="drafts")
    
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
