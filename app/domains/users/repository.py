from sqlalchemy.orm import Session
from typing import Optional, List
from app.domains.users.models import User, SocialAccount
from app.domains.users.schemas import UserCreate

class UserRepository:
    """
    User Repository (DAL - Data Access Layer)
    - User 및 SocialAccount 데이터베이스 접근을 담당합니다.
    """
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: int) -> Optional[User]:
        """ID로 사용자 조회"""
        return self.db.query(User).filter(User.id == user_id).first()

    def get_by_email(self, email: str) -> Optional[User]:
        """이메일로 사용자 조회"""
        return self.db.query(User).filter(User.email == email).first()
    
    def get_social_account(self, provider: str, provider_id: str) -> Optional[SocialAccount]:
        """소셜 제공자 및 ID로 소셜 계정 조회"""
        return self.db.query(SocialAccount).filter(
            SocialAccount.provider == provider,
            SocialAccount.provider_id == provider_id
        ).first()

    def create_user(self, email: str, nickname: Optional[str] = None) -> User:
        """신규 사용자 생성"""
        db_user = User(email=email, nickname=nickname)
        self.db.add(db_user)
        self.db.commit()
        self.db.refresh(db_user)
        return db_user

    def link_social_account(self, user_id: int, provider: str, provider_id: str) -> SocialAccount:
        """사용자에게 소셜 계정 연결"""
        social_acc = SocialAccount(
            user_id=user_id,
            provider=provider,
            provider_id=provider_id
        )
        self.db.add(social_acc)
        self.db.commit()
        self.db.refresh(social_acc)
        return social_acc
