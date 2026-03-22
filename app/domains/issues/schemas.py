from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, computed_field
from app.domains.publishers.schemas import PublisherAnalysis

class ClaimCardResponse(BaseModel):
    """주장 카드 응답 스키마"""
    id: int
    press: str
    title: str
    claim: str
    evidence: Optional[str] = None
    url: Optional[str] = None

    class Config:
        from_attributes = True

class IssueAnalysisResponse(BaseModel):
    """이슈 상세 분석 응답 (고도화 버전)"""
    id: int
    name: str
    description: Optional[str] = None
    background: Optional[str] = None
    core_contentions: Optional[str] = None # JSON string
    media_ratio: Optional[str] = None # JSON string
    created_at: datetime

    # 해당 이슈와 관련된 모든 주장 카드 리스트
    claim_cards: List[ClaimCardResponse] = []

    class Config:
        from_attributes = True

class IssueDraftResponse(BaseModel):
    """이슈 상세 분석 응답 (고도화 버전)"""
    id: int
    name: str
    description: Optional[str] = None
    background: Optional[str] = None
    core_contentions: Optional[str] = None # JSON string
    media_ratio: Optional[str] = None # JSON string
    created_at: datetime
    pre_generated_draft: Optional[str] = None
    # 해당 이슈와 관련된 모든 주장 카드 리스트
    claim_cards: List[ClaimCardResponse] = []

    class Config:
        from_attributes = True


class IssueFeedItem(BaseModel):
    """피드용 이슈 응답 스키마 (TOP 10 + 차트아웃 20개 공통)"""
    id: int
    name: str
    description: Optional[str] = None
    article_count: int
    rank: Optional[int] = None           # 현재(또는 최고) 순위
    created_at: datetime

    # 1순위 이슈 전용: 기사 이미지 URL 목록
    image_urls: List[str] = []           # 소속 기사들의 이미지 URL (1위 이슈만 채워짐)

    # 차트아웃 이슈 전용 필드
    is_chart_out: bool = False            # OUT 뱃지 표시 여부
    peak_rank: Optional[int] = None      # 최고 순위 (ex. 최고 3위)
    chart_out_minutes: Optional[int] = None  # 차트아웃 후 경과 시간(분)

    class Config:
        from_attributes = True


class IssueFeedResponse(BaseModel):
    """30개 이슈를 두 섹션으로 나눈 피드 응답"""
    top_issues: List[IssueFeedItem]       # 최신 생성 순 10개
    chart_out_issues: List[IssueFeedItem] # 차트아웃 20개

    class Config:
        from_attributes = True
