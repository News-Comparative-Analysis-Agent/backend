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
    core_contentions: Optional[str] = None
    background: Optional[str] = None
    issue_type: Optional[str] = None
    created_at: datetime
    
    # 인용 정보 매핑 (마커 인덱스 -> 기사 ID)
    description_citations: Optional[Dict[str, int]] = {}
    background_citations: Optional[Dict[str, int]] = {}

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
    issue_type: Optional[str] = None
    created_at: datetime
    pre_generated_draft: Optional[str] = None
    
    # 인용 정보 매핑 (마커 인덱스 -> 기사 ID)
    description_citations: Optional[Dict[str, int]] = {}
    background_citations: Optional[Dict[str, int]] = {}
    # 해당 이슈와 관련된 모든 주장 카드 리스트
    claim_cards: List[ClaimCardResponse] = []

    # 해당 이슈와 관련된 이미지 URL 리스트
    image_urls: List[str] = []

    class Config:
        from_attributes = True


class ArticleBasicInfo(BaseModel):
    title: str
    publisher: str

class IssueFeedItem(BaseModel):
    """피드용 이슈 응답 스키마"""
    id: int
    name: str
    description: Optional[str] = None
    issue_type: Optional[str] = None
    article_count: int
    rank: Optional[int] = None           # 중요도(기사 수 등)에 따른 순위
    created_at: datetime

    # 각 이슈에 묶인 기사 리스트
    articles: List[ArticleBasicInfo] = []

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
    total_count: int                      # 전체 이슈 수
    page: int                             # 현재 페이지
    page_size: int                        # 페이지당 아이템 수
    total_pages: int                      # 전체 페이지 수
    today_article_count: int = 0          # 오늘 수집된 총 기사 수
    today_issue_count: int = 0            # 오늘 생성된 총 이슈 수

    class Config:
        from_attributes = True


class IssueTimelineItem(BaseModel):
    """타임라인 내 개별 이슈 아이템"""
    id: int
    name: str # 이슈명
    phase: Optional[str] = "발생"
    conflict_summary: Optional[str] = None
    issue_type: Optional[str] = None
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
    root_issue_id: Optional[int] = None
    root_issue_name: Optional[str] = None
    timeline: List[IssueTimelineItem]

    class Config:
        from_attributes = True


class IssueFeedLegacyItem(BaseModel):
    """레거시 피드용 이슈 응답 스키마"""
    id: int
    name: str
    description: Optional[str] = None
    issue_type: Optional[str] = None
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

class HeadlineRecommendationResponse(BaseModel):
    """초안 기반 헤드라인 추천 응답"""
    headlines: List[str]

class DailyStatsResponse(BaseModel):
    """당일 서비스 통계 응답 스키마"""
    article_count: int
    issue_count: int
    publisher_count: int
    critique_count: int
    last_updated_at: datetime

    class Config:
        from_attributes = True

