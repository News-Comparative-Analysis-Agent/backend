from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


# ==========================================
# Citation (인용 출처) 관련 Schema
# ==========================================
class CitationItem(BaseModel):
    """기사 본문의 인용 마커 [N]에 대응하는 출처 메타데이터"""
    id: int
    press: str           # 언론사명
    title: str           # 사설 제목
    url: str             # 원문 기사 URL
    published_at: str    # 발행일 (YYYY-MM-DD)
    article_id: Optional[int] = None  # lazy-load용 기사 ID
    quote: str           # 본문에서 인용된 문장 (팝업 하이라이팅 대상)

class ArticleBodyResponse(BaseModel):
    """기사 원문 lazy-load 응답"""
    article_id: int
    raw_content: str

class DraftWithCitationsResponse(BaseModel):
    """기사 초안 + 인용 출처 배열 응답"""
    issue_id: int
    title: str
    article_body: str              # [N] 마커가 삽입된 본문
    citations: List[CitationItem]  # 언론사별 출처 배열


# ==========================================
# Chat (채팅) 관련 Schema
# ==========================================
class ChatAIOutputSchema(BaseModel):
    response: str = Field(description="수정 방향이나 피드백, 안내 멘트 등 사용자에게 전달할 대화 내용")
    modified_content: Optional[str] = Field(description="사용자가 글 내용 수정을 요구한 경우, 수정이 완료된 기사 초안 전체 텍스트. 전체 길이가 보존되어야 합니다. 수정을 원하지 않고 단순 질문만 한 경우에는 null")

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
    issue_id: Optional[int] = None # DB에서 기사 생성본을 가져오기 위한 파라미터
    
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

class ReviewScoreItem(BaseModel):
    score: int
    max_score: int
    detail: str

class ReviewScores(BaseModel):
    fairness: ReviewScoreItem
    faithfulness: ReviewScoreItem
    harmlessness: ReviewScoreItem
    total_score: int
    hate_speech_list: List[str] = []
    distortions_count: int = 0

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
    scores: ReviewScores
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
    content: Optional[str] = None # 선택적으로 초안 내용도 함께 저장 가능

class SaveDraftResponse(BaseModel):
    message: str
    draft_id: int

class WorkspaceDraftSummary(BaseModel):
    """내 작업실 목록 조회를 위한 간략한 초안 정보"""
    issue_id: int
    title: str
    updated_at: datetime

    class Config:
        from_attributes = True

class DraftUpdate(BaseModel):
    """초안 내용 수정 요청 (이슈 기준)"""
    content: str
