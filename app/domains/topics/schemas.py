from pydantic import BaseModel
from typing import List, Optional, Any
from datetime import datetime

class TopicBase(BaseModel):
    name: str # 주제명
    keywords: List[str] = [] # 키워드 리스트
    graph_data: Optional[Any] = None # 네트워크 차트용 데이터 (JSON)

class TopicCreate(TopicBase):
    pass

class TopicResponse(TopicBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
