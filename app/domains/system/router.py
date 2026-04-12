from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.domains.system.service import SystemService
from app.domains.system.schemas import SystemSettingsResponse, SystemSettingsUpdate

router = APIRouter()

@router.get("/settings", 
            response_model=SystemSettingsResponse,
            summary="시스템 설정 조회",
            description="LLM 모드 등 시스템의 전역 설정을 조회합니다.")
def get_system_settings(db: Session = Depends(get_db)):
    service = SystemService(db)
    return service.get_settings()


@router.patch("/settings", 
              response_model=SystemSettingsResponse,
              summary="시스템 설정 업데이트",
              description="LLM 모드 등 시스템의 전역 설정을 업데이트합니다.")
def update_system_settings(
    settings_update: SystemSettingsUpdate, 
    db: Session = Depends(get_db)):
    """
    llm 모드 변경
    """
    service = SystemService(db)
    return service.update_settings(settings_update)
