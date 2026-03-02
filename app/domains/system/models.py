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

class ExecutionLog(Base):
    """
    작업 실행 이력(Execution Log) 테이블
    - 크롤링, 클러스터링 등 주요 백그라운드 작업의 실행 상태와 결과를 기록합니다.
    """
    __tablename__ = "execution_logs"

    id = Column(Integer, primary_key=True, index=True)
    job_type = Column(String, nullable=False, index=True) # 'crawl', 'cluster' 등
    status = Column(String, default="running", index=True) # 'running', 'success', 'failed'
    
    mode = Column(String) # 실행 시의 LLM 모드
    
    # 처리 결과 요약 (예: {"saved": 10, "skipped": 5})
    result_summary = Column(JSONB, default={}) 
    
    # 상세 로그 또는 에러 메시지
    logs = Column(Text)
    
    started_at = Column(DateTime, default=func.now())
    finished_at = Column(DateTime)
