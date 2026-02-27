import os
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from app.core.database import get_db
from app.domains.users.models import User
from app.domains.users.service import UserService
from app.domains.users.schemas import TokenResponse
from app.core.security import create_access_token


router = APIRouter()

# .env 로드
load_dotenv()

@router.get("/login/kakao")
async def login_kakao(code: str, db: Session = Depends(get_db)):
    """
    카카오 OAuth 로그인 콜백 엔드포인트
    - 인가 코드를 받아 카카오 토큰 및 유저 정보를 획득하고 통합 로그인을 처리합니다.
    """
    # 환경 변수 직접 로드
    CLIENT_ID = os.getenv("KAKAO_CLIENT_ID", "").strip().strip('"').strip("'")
    REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI", "").strip().strip('"').strip("'")
    
    if not CLIENT_ID or not REDIRECT_URI:
        raise HTTPException(status_code=500, detail="카카오 OAuth 설정이 누락되었습니다.")

    service = UserService(db)
    try:
        print("라우터 진입 code: ", code)
        # 1. 액세스 토큰 획득
        access_token = await service.get_kakao_access_token(code, CLIENT_ID, REDIRECT_URI)
        # 2. 유저 정보 획득
        kakao_info = await service.get_kakao_user_info(access_token)
        
        email = kakao_info.get("kakao_account", {}).get("email")
        provider_id = str(kakao_info.get("id"))
        nickname = kakao_info.get("properties", {}).get("nickname")
        
        print("email: ", email)
        print("provider_id: ", provider_id)
        print("nickname: ", nickname)
        if not email:
            raise HTTPException(status_code=400, detail="카카오 이메일 동의가 필요합니다.")

        # 3. 통합 로그인 처리 (이메일이 같으면 기존 계정에 연결됨)
        user = service.social_login(email, "kakao", provider_id, nickname)
        
        # 4. JWT 발행
        jwt_token = create_access_token(subject=user.id)
        print("jwt_token: ", jwt_token)
        return {
            "access_token": jwt_token,
            "token_type": "bearer",
            "user": user
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/login/google", response_model=TokenResponse)
async def google_login(id_token: str, db: Session = Depends(get_db)):
    """
    구글 OAuth 로그인 API
    - 프론트엔드에서 전달받은 구글 ID 토큰을 검증하고 통합 로그인을 수행합니다.
    """
    service = UserService(db)
    try:
        print("구글 로그인 api 진입 --- id_token: ", id_token)
        # 1. 구글 토큰 검증
        google_info = await service.verify_google_token(id_token)
        
        email = google_info.get("email")
        provider_id = google_info.get("sub") # 구글의 고유 고정 ID
        nickname = google_info.get("name")
        print("email: ", email)
        print("provider_id: ", provider_id)
        print("nickname: ", nickname)
        if not email:
            raise HTTPException(status_code=400, detail="구글 이메일 정보가 필요합니다.")

        # 2. 통합 로그인 처리
        user = service.social_login(email, "google", provider_id, nickname)
        
        # 3. JWT 발행
        jwt_token = create_access_token(subject=user.id)
        
        return {
            "access_token": jwt_token,
            "token_type": "bearer",
            "user": user
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))