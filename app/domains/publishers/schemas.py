from pydantic import BaseModel
from typing import List, Optional

class PublisherBase(BaseModel):
    name: str
    code: Optional[str] = None

class PublisherResponse(PublisherBase):
    id: int

    class Config:
        from_attributes = True

from app.domains.articles.schemas import ArticleResponse

class PublisherAnalysis(BaseModel):
    """이슈 상세 분석 시 사용되는 언론사별 분석 데이터"""
    publisher_id: int
    publisher_name: str
    articles: List[ArticleResponse] # 해당 언론사의 상세 기사 리스트 (JSON/DTO)
    article_count: int

# Pydantic V2에서는 자동으로 처리되지만, 명시적 관리를 위해 유지할 수 있음
# PublisherAnalysis.model_rebuild()
