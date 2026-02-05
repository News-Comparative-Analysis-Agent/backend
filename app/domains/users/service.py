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

    # 소셜 로그인/회원가입 및 토큰 발급
    def login_with_oauth(self, user_data: UserCreate) -> TokenResponse:
        """
        소셜 로그인 처리 및 JWT 발급
        """
        # 1. 기존 유저 확인 (Provider ID 기준)
        user = self.repository.get_by_provider_id(user_data.provider, user_data.provider_id)
        
        # 2. 없다면 이메일로 확인
        if not user:
            user = self.repository.get_by_email(user_data.email)
            if not user:
                # 3. 신규 생성
                user = self.repository.create(user_data)
        
        # 4. JWT 발급
        access_token = create_access_token(data={"sub": str(user.id), "email": user.email})
        
        return TokenResponse(
            access_token=access_token,
            user=UserResponse.from_orm(user)
        )

    # OAuth 외부 API 연동 로직
    async def get_google_user_info(self, code: str) -> Optional[Dict[str, Any]]:
        """
        구글 인가 코드를 이용해 유저 정보를 가져옵니다.
        """
        async with httpx.AsyncClient() as client:
            token_url = "https://oauth2.googleapis.com/token"
            token_data = {
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            }
            token_res = await client.post(token_url, data=token_data)
            if token_res.status_code != 200:
                return None
            
            access_token = token_res.json().get("access_token")
            
            user_info_url = "https://www.googleapis.com/oauth2/v3/userinfo"
            headers = {"Authorization": f"Bearer {access_token}"}
            user_res = await client.get(user_info_url, headers=headers)
            if user_res.status_code != 200:
                return None
            
            return user_res.json()

    async def get_kakao_user_info(self, code: str) -> Optional[Dict[str, Any]]:
        """
        카카오 인가 코드를 이용해 유저 정보를 가져옵니다.
        """
        async with httpx.AsyncClient() as client:
            token_url = "https://kauth.kakao.com/oauth/token"
            token_data = {
                "grant_type": "authorization_code",
                "client_id": settings.KAKAO_CLIENT_ID,
                "client_secret": settings.KAKAO_CLIENT_SECRET,
                "redirect_uri": settings.KAKAO_REDIRECT_URI,
                "code": code,
            }
            token_res = await client.post(token_url, data=token_data)
            if token_res.status_code != 200:
                return None
            
            access_token = token_res.json().get("access_token")
            
            user_info_url = "https://kapi.kakao.com/v2/user/me"
            headers = {"Authorization": f"Bearer {access_token}"}
            user_res = await client.get(user_info_url, headers=headers)
            if user_res.status_code != 200:
                return None
            
            return user_res.json()
