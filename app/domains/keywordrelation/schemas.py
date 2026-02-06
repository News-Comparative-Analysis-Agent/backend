from pydantic import BaseModel
from typing import List

class GraphNode(BaseModel):
    id: str # 키워드

class GraphLink(BaseModel):
    source: str
    target: str
    value: int # 빈도수

class GraphData(BaseModel):
    nodes: List[GraphNode]
    links: List[GraphLink]
