from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.domains.users.schemas import UserCreate, UserResponse
from app.domains.users.service import UserService

router = APIRouter()

@router.post("/login/oauth", response_model=UserResponse)
def login_oauth(user_data: UserCreate, db: Session = Depends(get_db)):
    """
    OAuth 소셜 로그인/회원가입 API
    - 소셜 제공자 정보를 받아 가입 여부를 확인하고, 없으면 생성(가입) 후 정보를 반환합니다.
    """
    service = UserService(db)
    return service.get_or_create_user(user_data)

@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db)):
    """
    사용자 정보 조회 API
    """
    service = UserService(db)
    user = service.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
