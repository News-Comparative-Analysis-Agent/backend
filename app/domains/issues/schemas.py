from pydantic import BaseModel
from typing import List, Optional, Any
from datetime import datetime

class GraphNode(BaseModel):
    id: str # 키워드

class GraphLink(BaseModel):
    source: str
    target: str
    value: int # 빈도수

class GraphData(BaseModel):
    nodes: List[GraphNode]
    links: List[GraphLink]

class IssueResponse(BaseModel):
    id: int
    name: str # 이슈명
    article_count: int # 관련 기사 수
    rank: Optional[int] = None # 순위
    created_at: datetime

    class Config:
        from_attributes = True
