from datetime import datetime
from typing import List, Optional, Dict
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
    created_at: datetime

    # 해당 이슈와 관련된 모든 주장 카드 리스트
    claim_cards: List[ClaimCardResponse] = []

    # 해당 이슈와 관련된 이미지 URL 리스트
    image_urls: List[str] = []

    class Config:
        from_attributes = True

class IssueDraftResponse(BaseModel):
    """이슈 상세 분석 응답 (고도화 버전)"""
    id: int
    name: str
    description: Optional[str] = None
    background: Optional[str] = None
    created_at: datetime
    pre_generated_draft: Optional[str] = None
    # 해당 이슈와 관련된 모든 주장 카드 리스트
    claim_cards: List[ClaimCardResponse] = []

    # 해당 이슈와 관련된 이미지 URL 리스트
    image_urls: List[str] = []

    class Config:
        from_attributes = True


class IssueFeedItem(BaseModel):
    """피드용 이슈 응답 스키마"""
    id: int
    name: str
    description: Optional[str] = None
    article_count: int
    rank: Optional[int] = None           # 중요도(기사 수 등)에 따른 순위
    created_at: datetime

    # 기사 대표 이미지 URL 목록
    image_urls: List[str] = []           # 소속 기사들의 이미지 URL

    class Config:
        from_attributes = True


class IssueGroupedResponse(BaseModel):
    """날짜별로 그룹화된 이슈 피드 응답"""
    data: Dict[str, List[IssueFeedItem]]  # 키: YYYY-MM-DD, 값: 해당 날짜의 이슈 리스트

    class Config:
        from_attributes = True


class IssueFeedResponse(BaseModel):
    """날짜별 이슈 피드 응답 (단일 리스트)"""
    date: str                             # 조회된 날짜 (YYYY-MM-DD)
    issues: List[IssueFeedItem]           # 해당 날짜의 이슈 목록

    class Config:
        from_attributes = True


class IssueTimelineItem(BaseModel):
    """타임라인 내 개별 이슈 아이템"""
    id: int
    name: str # 이슈명
    article_count: int # 관련 기사 수
    created_at: datetime
    
    # 기사 대표 이미지 URL 목록
    image_urls: List[str] = []
    
    class Config:
        from_attributes = True


class IssueTimelineResponse(BaseModel):
    """특정 이슈에 대한 타임라인 (유사한 이슈 모음)"""
    target_issue_id: int
    target_issue_name: str
    timeline: List[IssueTimelineItem]

    class Config:
        from_attributes = True


class IssueFeedLegacyItem(BaseModel):
    """레거시 피드용 이슈 응답 스키마"""
    id: int
    name: str
    description: Optional[str] = None
    article_count: int
    rank: Optional[int] = None
    created_at: datetime
    image_urls: List[str] = []
    
    # 레거시 전용 필드
    is_chart_out: bool = False
    peak_rank: Optional[int] = None
    chart_out_minutes: Optional[int] = None

    class Config:
        from_attributes = True


class IssueFeedLegacyResponse(BaseModel):
    """레거시 이슈 피드 응답 (TOP 10 + 차트아웃 20)"""
    top_issues: List[IssueFeedLegacyItem]
    chart_out_issues: List[IssueFeedLegacyItem]

    class Config:
        from_attributes = True

