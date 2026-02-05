from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/aigent_db"
    
    # Security
    SECRET_KEY: str = "your-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Naver API
    NAVER_CLIENT_ID: Optional[str] = None
    NAVER_CLIENT_SECRET: Optional[str] = None
    
    # Google OAuth
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/user/auth/google/callback"
    
    # Kakao OAuth
    KAKAO_CLIENT_ID: Optional[str] = None
    KAKAO_CLIENT_SECRET: Optional[str] = None
    KAKAO_REDIRECT_URI: str = "http://localhost:8000/user/auth/kakao/callback"
    
    # OpenAI
    OPENAI_API_KEY: Optional[str] = None

    class Config:
        env_file = ".env"

settings = Settings()
