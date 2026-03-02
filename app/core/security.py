import os
from datetime import datetime, timedelta
from typing import Any, Union, Optional
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from app.core.database import get_db
from app.domains.users.models import User

# .env 파일 로드
load_dotenv()

# 환경 변수 직접 로드 (config.py 제거 대응)
# SECRET_KEY = os.getenv("SECRET_KEY", "dev_secret_key").strip().strip('"').strip("'")
# ALGORITHM = os.getenv("ALGORITHM", "HS256").strip().strip('"').strip("'")
# ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24 * 7))

# OAuth2 설정
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="user/login/kakao", auto_error=False)

def create_access_token(subject: Union[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    JWT 액세스 토큰을 생성합니다.
    :param subject: 토큰의 주체 (user_id)
    :param expires_delta: 토큰 만료 시간
    :return: 암호화된 JWT 문자열
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """
    현재 로그인한 사용자를 조회합니다. (JWT 토큰 검증)
    - 로그인이 되어있지 않거나 토큰이 유효하지 않으면 401 Unauthorized 에러를 발생시킵니다.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="로그인이 필요한 서비스입니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if not token:
        raise credentials_exception

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise credentials_exception
    return user
