from sqlalchemy.orm import Session
from app.domains.users.repository import UserRepository
from app.domains.users.schemas import UserCreate, UserResponse

class UserService:
    """
    User Service (Business Layer)
    - 사용자와 관련된 '업무 로직'을 처리합니다.
    - 예: "없으면 만들고, 있으면 가져와라", "권한을 체크해라" 등
    """
    def __init__(self, db: Session):
        self.repository = UserRepository(db)

    def get_user(self, user_id: int) -> UserResponse:
        """ID로 사용자 정보를 가져옵니다."""
        user = self.repository.get_by_id(user_id)
        if not user:
            return None
        return user

    def get_or_create_user(self, user_data: UserCreate) -> UserResponse:
        """
        소셜 로그인 전용 로직
        1. 이메일로 기존 가입자인지 확인
        2. 가입자라면 -> 정보 반환 (Login)
        3. 아니라면 -> 신규 생성 후 반환 (Register)
        """
        existing_user = self.repository.get_by_email(user_data.email)
        if existing_user:
            return existing_user
        
        # 신규 유저 생성
        new_user = self.repository.create(user_data)
        return new_user
