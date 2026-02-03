from pydantic import BaseModel
from typing import List, Optional, Any
from datetime import datetime
from app.domains.keywordrelation.schemas import GraphNode, GraphLink, GraphData

class IssueResponse(BaseModel):
    id: int
    name: str # 이슈명
    article_count: int # 관련 기사 수
    rank: Optional[int] = None # 순위
    created_at: datetime

    class Config:
        from_attributes = True
