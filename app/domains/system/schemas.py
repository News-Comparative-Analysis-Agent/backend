from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class SystemSettingsBase(BaseModel):
    llm_mode: str

class SystemSettingsUpdate(BaseModel):
    llm_mode: Optional[str] = None

class SystemSettingsResponse(SystemSettingsBase):
    id: int
    updated_at: datetime

    class Config:
        from_attributes = True