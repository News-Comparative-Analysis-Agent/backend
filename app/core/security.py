from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.domains.users.repository import UserRepository
from app.domains.users.models import User

# OAuth2 인증 방식 설정 (Bearer 토큰 방식)
# tokenUrl은 스웨거(Swagger) 문서에서 로그인 엔드포인트를 지정하는 용도입니다.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="user/auth/login") 

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    사용자 정보를 담은 JWT Access Token을 생성합니다.
    - data: 토큰에 담을 정보 (유저 ID 등)
    - expires_delta: 토큰 만료 시간
    """
    to_encode = data.copy()
    
    # 만료 시간 설정
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    
    # JWT 토큰 발행 (Secret Key와 Algorithm 사용)
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[dict]:
    """
    JWT 토큰을 해독하고 유효성을 검증합니다.
    - 유효하지 않거나 만료된 토큰인 경우 None을 반환합니다.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    FastAPI 의존성 주입용 함수:
    인증이 필요한 API에서 현재 로그인된 유저 객체를 가져옵니다.
    
    사용 예: @router.get("/me") def me(user: User = Depends(get_current_user)): ...
    """
    # 인증 실패 시 발생시킬 공통 예외
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증 자격 증명을 확인할 수 없습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # 1. 토큰 해독
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    
    # 2. 토큰에서 유저 식별자(sub) 추출
    user_id: str = payload.get("sub")
    if user_id is None:
        raise credentials_exception
        
    # 3. DB에서 실제 유저가 존재하는지 조회
    repo = UserRepository(db)
    user = repo.get_by_id(int(user_id))
    if user is None:
        raise credentials_exception
        
    # 4. 검증된 유저 객체 반환
    return user
