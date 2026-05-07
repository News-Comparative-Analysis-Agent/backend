from pydantic import BaseModel, HttpUrl
from typing import List, Optional, Dict, Any
from datetime import datetime

class ArticleBase(BaseModel):
    title: str
    url: str
    published_at: datetime
    reporter: Optional[str] = None # 기자 이름
    image_url: Optional[str] = None # 1위 기사용 대표 이미지

class ArticleCreate(ArticleBase):
    publisher_id: Optional[int] = None

class ArticleResponse(ArticleBase):
    id: int
    publisher_id: Optional[int]
    
    # 추가 정보 (Relation)
    publisher_name: Optional[str] = None 
    issue_type: Optional[str] = None
    article_type: Optional[str] = None

    class Config:
        from_attributes = True

class ArticleDetail(ArticleResponse):
    """상세 조회 시 본문 포함"""
    content: Optional[str] = None 

class ArticleGroupedResponse(BaseModel):
    """날짜별/언론사별로 그룹화된 기사 피드 응답"""
    data: Dict[str, Dict[str, List[ArticleResponse]]]  # 키1: 날짜, 키2: 언론사명, 값: 기사 리스트

    class Config:
        from_attributes = True
