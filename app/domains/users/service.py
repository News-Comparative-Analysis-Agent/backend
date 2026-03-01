import os
import httpx
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from app.domains.users.models import User
from app.domains.users.repository import UserRepository
from app.domains.users.schemas import UserCreate, UserResponse, TokenResponse

class UserService:
    """
    User Service (Business Layer)
    - 유저 관리 및 OAuth 인증 통합 처리
    """
    def __init__(self, db: Session):
        self.repository = UserRepository(db)

    # 사용자 조회
    def get_user(self, user_id: int) -> Optional[User]:
        """ID로 사용자 정보를 가져옵니다."""
        return self.repository.get_by_id(user_id)

    def social_login(self, email: str, provider: str, provider_id: str, nickname: Optional[str] = None) -> User:
        """
        소셜 로그인 통합 로직
        1. 해당 소셜 계정(Provider + ID)이 이미 연동되어 있는지 확인
        2. 없다면 동일한 이메일을 가진 기존 사용자가 있는지 확인 (계정 통합)
        3. 신규 사용자라면 새로 생성 후 소셜 계정 연동
        """
        # 1. 기존 소셜 계정 확인
        social_acc = self.repository.get_social_account(provider, provider_id)
        if social_acc:
            return self.repository.get_by_id(social_acc.user_id)

        # 2. 이메일 기반 기존 유저 확인 (계정 통합 핵심)
        user = self.repository.get_by_email(email)
        if not user:
            # 3. 신규 유저 생성
            user = self.repository.create_user(email, nickname)
        
        # 4. 소셜 계정 연결
        self.repository.link_social_account(user.id, provider, provider_id)
        
        return user

    async def get_kakao_access_token(self, code: str, client_id: str, redirect_uri: str) -> str:
        """카카오 인가 코드로 액세스 토큰 획득"""
        url = "https://kauth.kakao.com/oauth/token"
        data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code": code,
            "client_secret": os.getenv("KAKAO_CLIENT_SECRET")
        }
        print("get_kakao_access_token메서드 진입 \n data: ", data)
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data)
            print("response status: ", response.status_code)
            print("response body: ", response.text) # 상세 에러 확인용
            response.raise_for_status()
            return response.json().get("access_token")

    async def get_kakao_user_info(self, access_token: str) -> Dict[str, Any]:
        """액세스 토큰으로 카카오 유저 정보 획득"""
        url = "https://kapi.kakao.com/v2/user/me"
        print("get_kakao_user_info메서드 진입 \n access_token: ", access_token)
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            print("response: ", response)
            response.raise_for_status()
            return response.json()

    async def verify_google_token(self, id_token: str) -> Dict[str, Any]:
        """구글 ID 토큰 검증 및 유저 정보 획득"""
        # Google ID Token은 Google의 tokeninfo 엔드포인트를 통해 검증 가능합니다.
        url = f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            if response.status_code != 200:
                raise Exception("유효하지 않은 구글 토큰입니다.")
            return response.json()

