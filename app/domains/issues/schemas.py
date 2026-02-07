from datetime import datetime
from app.domains.keywordrelation.schemas import GraphNode, GraphLink, GraphData
from app.domains.publishers.schemas import PublisherAnalysis

class IssueResponse(BaseModel):
    id: int
    name: str # 이슈명
    article_count: int # 관련 기사 수
    rank: Optional[int] = None # 순위
    created_at: datetime

    class Config:
        from_attributes = True

class IssueAnalysisResponse(BaseModel):
    """이슈 상세 분석 응답"""
    issue_id: int
    issue_name: str
    publisher_analyses: List[PublisherAnalysis]
