from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
from app.domains.publishers.schemas import PublisherAnalysis

class IssueResponse(BaseModel):
    id: int
    name: str # 이슈명
    description: Optional[str] = None # 이슈 배경
    article_count: int # 관련 기사 수
    rank: Optional[int] = None # 순위
    pre_generated_draft: Optional[str] = None # 미리 생성된 초안
    created_at: datetime

    class Config:
        from_attributes = True

class ClaimCardResponse(BaseModel):
    """주장 카드 응답 스키마"""
    id: int
    press: str
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
    pre_generated_draft: Optional[str] = None
    created_at: datetime
    
    # 해당 이슈와 관련된 모든 주장 카드 리스트
    claim_cards: List[ClaimCardResponse] = []

    class Config:
        from_attributes = True
