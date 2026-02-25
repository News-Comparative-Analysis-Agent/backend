# app/scroller/schemas.py
from pydantic import BaseModel

class CrawlResponse(BaseModel):
    status: str
    message: str
    saved_count: int
    skipped_count: int

class ClusterResponse(BaseModel):
    status: str
    message: str
    saved_issue_count: int

class ResetResponse(BaseModel):
    status: str
    message: str

# NLP 기반 뉴스 검색용 DTO, dto!!
class SearchRequest(BaseModel):
    query: str

class SearchResponse(BaseModel):
    success: bool
    data: dict = None
    message: str = None
