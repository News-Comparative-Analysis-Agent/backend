from sqlalchemy.orm import Session
from app.domains.users.repository import UserRepository
from app.domains.users.schemas import UserCreate, UserResponse

class UserService:
    """
    User Service (Business Layer)
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

    # 소셜 로그인/회원가입
    def get_or_create_user(self, user_data: UserCreate) -> UserResponse:
        """
        소셜 로그인 전용 로직
        1. 이메일로 기존 가입자인지 확인
        2. 가입자라면 -> 정보 반환 (Login)
        3. 아니라면 -> 신규 생성 후 반환 (Register)
        """
        # 1. 이메일로 기존 유저 확인
        existing_user = self.repository.get_by_email(user_data.email)
        
        if existing_user:
            # 2-1. 이미 가입된 유저라면, 소셜 로그인 정보(Provider)가 일치하는지 확인 (선택 사항)
            # 여기서는 단순히 기존 유저를 반환하여 로그인을 처리합니다.
            # 추후 필요 시 "구글로 가입된 계정입니다. 구글로 로그인해주세요" 등의 예외 처리를 할 수 있습니다.
            return existing_user
        
        # 2-2. 가입되지 않은 유저라면 신규 생성 (Register)
        new_user = self.repository.create(user_data)
        return new_user
