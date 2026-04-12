from sqlalchemy.orm import Session
from app.domains.system.models import SystemSettings
from app.domains.system.schemas import SystemSettingsUpdate

class SystemService:
    def __init__(self, db: Session):
        self.db = db

    def get_settings(self) -> SystemSettings:
        """
        시스템 설정을 조회합니다. 
        만약 데이터가 없으면 기본값(id=1)으로 생성합니다.
        """
        settings = self.db.query(SystemSettings).filter(SystemSettings.id == 1).first()
        if not settings:
            settings = SystemSettings(id=1, llm_mode="gemini_only")
            self.db.add(settings)
            self.db.commit()
            self.db.refresh(settings)
        return settings

    def update_settings(self, settings_update: SystemSettingsUpdate) -> SystemSettings:
        """
        시스템 설정을 업데이트합니다.
        """
        settings = self.get_settings()
        
        if settings_update.llm_mode is not None:
            settings.llm_mode = settings_update.llm_mode
            
        self.db.commit()
        self.db.refresh(settings)
        return settings
