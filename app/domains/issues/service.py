from sqlalchemy.orm import Session
from typing import List, Dict
from app.domains.issues.repository import IssueRepository
from app.domains.issues.schemas import IssueResponse, IssueAnalysisResponse
from app.domains.articles.schemas import ArticleResponse
from app.domains.publishers.schemas import PublisherAnalysis
from fastapi import HTTPException
from collections import defaultdict

class IssueService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = IssueRepository(db)

    def get_daily_issues(self, limit: int = 10) -> List[IssueResponse]:
        """
        실시간 이슈 목록 조회
        """
        issues = self.repo.get_recent_issues(limit=limit)
        
        result = []
        for idx, issue in enumerate(issues):
            result.append(IssueResponse(
                id=issue.id,
                name=issue.name,
                description=issue.description,
                article_count=issue.total_count,
                rank=idx + 1,
                created_at=issue.created_at
            ))
            
        return result

    def get_daily_trends(self, limit: int = 10) -> List[IssueResponse]:
        """
        트렌드 이슈 목록 조회
        """
        issues = self.repo.get_top_issues(limit=limit)
        
        result = []
        for idx, issue in enumerate(issues):
            result.append(IssueResponse(
                id=issue.id,
                name=issue.name,
                description=issue.description,
                article_count=issue.total_count,
                rank=idx + 1,
                created_at=issue.created_at
            ))
            
        return result

    def get_issue_analysis(self, issue_id: int) -> IssueAnalysisResponse:
        """
        특정 이슈에 대한 언론사별 기사 묶음 상세 분석 데이터 제공
        """
        # 1. 이슈 기본 정보 조회
        issue = self.repo.get_by_id(issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="Issue not found")

        # 2. 관련 기사 및 언론사 데이터 조회
        articles = self.repo.get_articles_with_publisher(issue_id)
        
        # 3. 언론사별 그룹화 가공
        pub_groups = defaultdict(list)
        for art in articles:
            # ArticleResponse DTO로 변환하여 리스트에 추가
            art_dto = ArticleResponse(
                id=art.id,
                title=art.title,
                url=art.url,
                published_at=art.published_at,
                summary=art.summary,
                bias=art.bias,
                bias_score=art.bias_score,
                reporter=art.reporter,
                key_arguments=art.key_arguments,
                publisher_id=art.publisher_id,
                publisher_name=art.publisher.name
            )
            pub_groups[art.publisher].append(art_dto)

        publisher_analyses = []
        for publisher, art_dtos in pub_groups.items():
            publisher_analyses.append(PublisherAnalysis(
                publisher_id=publisher.id,
                publisher_name=publisher.name,
                articles=art_dtos, # 기사 DTO 리스트 (JSON 형태)
                article_count=len(art_dtos)
            ))

        return IssueAnalysisResponse(
            issue_id=issue.id,
            issue_name=issue.name,
            issue_description=issue.description,
            publisher_analyses=publisher_analyses
        )
