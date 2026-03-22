from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# ==========================================
# Stream 생성 시 Schema
# ==========================================
class StreamDraftRequest(BaseModel):
    issue_id: int

# ==========================================
# Chat (채팅) 관련 Schema
# ==========================================
class ChatMessage(BaseModel):
    role: str # "user" or "model" or "system"
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage] # 대화 내역
    draft_content: Optional[str] = "" # 현재 작성 중인 초안 내용 (Context)
    
class ChatResponse(BaseModel):
    response: str
    modified_content: Optional[str] = None # AI가 초안을 수정한 경우

# ==========================================
# Images (이미지 추출) 관련 Schema
# ==========================================
class ImageItem(BaseModel):
    url: str
    title: str
    publisher: str
    published_at: str

class GuidelineCheck(BaseModel):
    label: str
    passed: bool
    detail: str

class ArticleSourceItem(BaseModel):
    title: str
    publisher: str
    url: str
    published_at: str


class FinalReviewResponse(BaseModel):
    """이슈 상세 분석 응답 (고도화 버전)"""
    id: int
    name: str
    description: Optional[str] = None
    background: Optional[str] = None
    core_contentions: Optional[str] = None # JSON string
    created_at: datetime
    updated_at: datetime
    pre_generated_draft: Optional[str] = None
    sources: List[ArticleSourceItem] = [] # 신뢰도 점수 대신 소스 기사 목록만 직접 노출
    guideline_checks: List[GuidelineCheck]
    ai_opinion: str
    class Config:
        from_attributes = True

# ==========================================
# Similarity (표절 검사) 관련 Schema
# ==========================================
class SimilarityRequest(BaseModel):
    issue_id: int
    draft_text: str

class SimilarityResponse(BaseModel):
    score: int  # 0 to 100
    message: str
    status: str # 'safe', 'warning', 'critical'

# ==========================================
# Perspectives (관점 분석) 관련 Schema
# ==========================================
class ArticleInfo(BaseModel):
    id: int
    title: str
    url: str
    publisher: str
    published_at: str

class PerspectiveItem(BaseModel):
    publisher: str    # 언론사명 (예: 한겨레)
    summary: str      # Gemini analysis result
    articles: List[ArticleInfo]

class PerspectivesResponse(BaseModel):
    issue_id: int
    issue_name: str
    perspectives: List[PerspectiveItem]

# ==========================================
# Workspace (작업실 저장) 관련 Schema
# ==========================================
class SaveDraftRequest(BaseModel):
    issue_id: int

class SaveDraftResponse(BaseModel):
    message: str
    draft_id: int
