from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    """
    User 공통 속성
    - 읽기/쓰기 모든 시나리오에서 공통적으로 사용되는 필드
    """
    email: EmailStr
    nickname: Optional[str] = None

class UserCreate(UserBase):
    """
    회원가입/로그인 시도 시 필요한 데이터
    - 소셜 로그인 제공자 정보(provider, provider_id)가 필수입니다.
    """
    provider: str # 예: "google", "kakao"
    provider_id: str # 예: "1234567890"

class UserUpdate(BaseModel):
    """
    회원 정보 수정 시 사용되는 데이터
    - 수정 가능한 필드만 포함 (이메일, provider 정보 수정 불가)
    """
    nickname: Optional[str] = None

class UserResponse(UserBase):
    """
    클라이언트에게 반환되는 User 정보 (Response DTO)
    - DB의 ID와 생성일시 정보를 포함합니다.
    """
    id: int
    provider: str
    created_at: datetime

    class Config:
        from_attributes = True # ORM 객체를 Pydantic 모델로 변환 허용

class TokenResponse(BaseModel):
    """
    인증 성공 시 반환되는 토큰 정보
    """
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
