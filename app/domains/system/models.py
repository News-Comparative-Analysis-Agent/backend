from sqlalchemy import Column, Integer, String, DateTime, Text, func, JSON
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base

class SystemSettings(Base):
    """
    시스템 전역 설정 테이블
    - 관리자가 설정한 모드(LLM 모드 등)를 저장하며, 시스템 전체에 영향을 미칩니다.
    - 단일 레코드(id=1)만 사용하도록 권장됩니다.
    """
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    llm_mode = Column(String, default="gemini_only") # 글로벌 LLM 작동 모드
    
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
