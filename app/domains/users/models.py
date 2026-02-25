from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.core.database import Base

class User(Base):
    """
    사용자(User) 테이블
    - 이메일을 유일한 식별자로 사용하며, 구글, 카카오 계정을 연결할 수 있습니다.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True) # 사용자 이메일 (고유값)
    nickname = Column(String) # 사용자 닉네임
    
    created_at = Column(DateTime, default=func.now()) # 가입 일시

    # 관계 설정
    social_accounts = relationship("SocialAccount", back_populates="user", cascade="all, delete-orphan")

class SocialAccount(Base):
    """
    소셜 계정(Social Account) 테이블
    - 하나의 사용자가 여러 소셜 로그인 수단(Google, Kakao 등)을 가질 수 있도록 합니다.
    """
    __tablename__ = "social_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    provider = Column(String, nullable=False) # 로그인 제공자 (예: 'google', 'kakao')
    provider_id = Column(String, nullable=False) # 제공자 측의 유저 고유 ID (OAuth 토큰 키 등)
    
    created_at = Column(DateTime, default=func.now()) # 연결 일시

    # 관계 설정
    user = relationship("User", back_populates="social_accounts")
