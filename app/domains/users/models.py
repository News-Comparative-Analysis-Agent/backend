from sqlalchemy import Column, Integer, String, DateTime, func
from app.core.database import Base

class User(Base):
    """
    사용자(User) 테이블
    - OAuth 소셜 로그인을 통해 가입한 사용자 정보를 저장합니다.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True) # 사용자 이메일 (고유값)
    nickname = Column(String) # 사용자 닉네임
    
    # OAuth 정보
    provider = Column(String, nullable=False) # 로그인 제공자 (예: 'google', 'kakao')
    provider_id = Column(String, nullable=False) # 제공자 측의 유저 고유 ID
    
    created_at = Column(DateTime, default=func.now()) # 가입 일시
