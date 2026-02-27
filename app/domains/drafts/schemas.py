from pydantic import BaseModel
from typing import List, Optional

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
