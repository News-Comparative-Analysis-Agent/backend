import httpx
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from app.domains.users.repository import UserRepository
from app.domains.users.schemas import UserCreate, UserResponse, TokenResponse
from app.core.security import create_access_token
from app.core.config import settings

class UserService:
    """
    User Service (Business Layer)
    - 유저 관리 및 OAuth 인증 통합 처리
    """
    def __init__(self, db: Session):
        self.repository = UserRepository(db)

    # 사용자 조회
    def get_user(self, user_id: int) -> UserResponse:
        """ID로 사용자 정보를 가져옵니다."""
        user = self.repository.get_by_id(user_id)
        if not user:
            return None
        return user

