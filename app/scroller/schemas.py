# app/scroller/schemas.py
from pydantic import BaseModel
from enum import Enum
from typing import Optional

class LLMMode(str, Enum):
    GEMINI_ONLY = "gemini_only"
    LOCAL_PRIORITY = "local_priority"
    LOCAL_ONLY = "local_only"

class CrawlRequest(BaseModel):
    mode: Optional[LLMMode] = LLMMode.GEMINI_ONLY

class ClusterRequest(BaseModel):
    mode: Optional[LLMMode] = LLMMode.GEMINI_ONLY

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

class LLMModeUpdateRequest(BaseModel):
    mode: LLMMode

class SettingsResponse(BaseModel):
    status: str
    message: str
    current_mode: Optional[str] = None

# 로그 조회용 DTO
from typing import List

class LogFileItem(BaseModel):
    date: str
    filename: str
    size: int
    last_modified: str

class LogListResponse(BaseModel):
    status: str
    logs: List[LogFileItem]

class LogDetailResponse(BaseModel):
    status: str
    filename: str
    content: str
