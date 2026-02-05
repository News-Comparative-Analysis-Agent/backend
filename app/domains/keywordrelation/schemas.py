from pydantic import BaseModel
from typing import List
from datetime import date

class GraphNode(BaseModel):
    id: str # 키워드

class GraphLink(BaseModel):
    source: str
    target: str
    value: int # 빈도수

class GraphData(BaseModel):
    nodes: List[GraphNode]
    links: List[GraphLink]

class KeywordMentionPoint(BaseModel):
    date: date
    count: int # 언급량(빈도 합계)

class KeywordMentionResponse(BaseModel):
    keyword: str
    mentions: List[KeywordMentionPoint]
