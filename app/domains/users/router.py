from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.domains.users.service import UserService
from app.domains.users.schemas import UserCreate, TokenResponse, UserResponse
from app.core.security import get_current_user

router = APIRouter()

@router.get("/auth/google/callback", response_model=TokenResponse)
async def google_callback(code: str = Query(...), db: Session = Depends(get_db)):
    """
    구글 로그인 콜백
    """
    service = UserService(db)
    # 1. 구글 유저 정보 획득
    user_info = await service.get_google_user_info(code)
    if not user_info:
        raise HTTPException(status_code=400, detail="구글 인증 실패")
    
    # 2. 우리 서비스 유저 데이터 구성
    user_create = UserCreate(
        email=user_info.get("email"),
        nickname=user_info.get("name"),
        provider="google",
        provider_id=user_info.get("sub")
    )
    
    # 3. 로그인/회원가입 처리
    return service.login_with_oauth(user_create)

@router.get("/auth/kakao/callback", response_model=TokenResponse)
async def kakao_callback(code: str = Query(...), db: Session = Depends(get_db)):
    """
    카카오 로그인 콜백
    """
    service = UserService(db)
    # 1. 카카오 유저 정보 획득
    user_info = await service.get_kakao_user_info(code)
    if not user_info:
        raise HTTPException(status_code=400, detail="카카오 인증 실패")
    
    # 2. 우리 서비스 유저 데이터 구성
    kakao_account = user_info.get("kakao_account", {})
    profile = kakao_account.get("profile", {})
    
    user_create = UserCreate(
        email=kakao_account.get("email"),
        nickname=profile.get("nickname"),
        provider="kakao",
        provider_id=str(user_info.get("id"))
    )
    
    # 3. 로그인/회원가입 처리
    return service.login_with_oauth(user_create)

@router.get("/me", response_model=UserResponse)
def get_me(current_user: UserResponse = Depends(get_current_user)):
    """
    현재 로그인된 유저 정보 조회
    """
    return current_user
