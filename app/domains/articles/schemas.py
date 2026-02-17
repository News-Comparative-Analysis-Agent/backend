from pydantic import BaseModel, HttpUrl
from typing import List, Optional, Dict, Any
from datetime import datetime

class ArticleBase(BaseModel):
    title: str
    url: str
    published_at: datetime
    summary: Optional[str] = None
    bias: Optional[str] = None
    bias_score: Optional[float] = None
    reporter: Optional[str] = None # 기자 이름
    key_arguments: Optional[str] = None # 핵심 논점 (Text)

class ArticleCreate(ArticleBase):
    publisher_id: Optional[int] = None

class ArticleResponse(ArticleBase):
    id: int
    publisher_id: Optional[int]
    
    # 추가 정보 (Relation)
    publisher_name: Optional[str] = None 

    class Config:
        from_attributes = True

class ArticleDetail(ArticleResponse):
    """상세 조회 시 본문 포함"""
    content: Optional[str] = None 
