from sqlalchemy.orm import Session
from typing import Optional
from app.domains.users.models import User
from app.domains.users.schemas import UserCreate

class UserRepository:
    """
    User Repository (DAL - Data Access Layer)
    - 데이터베이스에 직접 접근하여 CRUD(Create, Read, Update, Delete)를 수행합니다.
    """
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: int) -> Optional[User]:
        """ID로 사용자 조회"""
        return self.db.query(User).filter(User.id == user_id).first()

    def get_by_email(self, email: str) -> Optional[User]:
        """이메일로 사용자 조회"""
        return self.db.query(User).filter(User.email == email).first()
    
    def get_by_provider_id(self, provider: str, provider_id: str) -> Optional[User]:
        """소셜 제공자 ID로 사용자 조회 (예: 구글의 고유 ID)"""
        return self.db.query(User).filter(
            User.provider == provider,
            User.provider_id == provider_id
        ).first()

    def create(self, user_data: UserCreate) -> User:
        """신규 사용자 생성 (INSERT)"""
        db_user = User(
            email=user_data.email,
            nickname=user_data.nickname,
            provider=user_data.provider,
            provider_id=user_data.provider_id,
            profile_image_url=user_data.profile_image_url
        )
        self.db.add(db_user)
        self.db.commit()
        self.db.refresh(db_user) # DB에서 생성된 ID, Date 등 업데이트
        return db_user
