from fastapi import HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Dict
from datetime import datetime, timezone, date as py_date, timedelta
from app.domains.issues.repository import IssueRepository
from app.domains.issues.schemas import (
    IssueFeedItem, IssueFeedResponse, IssueAnalysisResponse, 
    IssueDraftResponse, ClaimCardResponse, IssueGroupedResponse,
    IssueTimelineItem, IssueTimelineResponse,
    IssueFeedLegacyItem, IssueFeedLegacyResponse,
    HeadlineRecommendationResponse
)
from collections import defaultdict
from app.agents.utils import call_llm

class IssueService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = IssueRepository(db)
        
    def get_issue_analysis(self, issue_id: int) -> IssueAnalysisResponse:
        """
        특정 이슈에 대한 고도화된 분석 데이터(메타데이터 + 주장 카드) 제공
        """
        # 1. 이슈 기본 정보 및 분석 메타데이터 조회
        issue = self.repo.get_by_id(issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="해당 이슈를 찾을 수 없습니다.")
    
        # 2. 관련 주장 카드 데이터 조회
        claims = self.repo.get_claims_by_issue(issue_id)
    
        from app.domains.issues.schemas import ClaimCardResponse
        claim_cards = [
            ClaimCardResponse(
                id=c.id,
                press=c.press,
                title=c.article.title if c.article else "",
                claim=c.claim,
                evidence=c.evidence,
                url=c.article.url if c.article else None
            ) for c in claims
        ]
    
        # 3. 이미지 URL 조회
        image_urls = self.repo.get_image_urls_by_issue(issue_id)
    
        return IssueAnalysisResponse(
            id=issue.id,
            name=issue.name,
            description=issue.description,
            background=issue.background,
            core_contentions=issue.conflict_summary,
            issue_type=issue.issue_type,
            created_at=issue.created_at,
            claim_cards=claim_cards,
            image_urls=image_urls
        )

    def get_issue_draft(self, issue_id: int) -> IssueDraftResponse:
        """
        특정 이슈에 대한 고도화된 분석 데이터(메타데이터 + 주장 카드) 제공
        """
        # 1. 이슈 기본 정보 및 분석 메타데이터 조회
        issue = self.repo.get_by_id(issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="해당 이슈를 찾을 수 없습니다.")
    
        # 2. 관련 주장 카드 데이터 조회
        claims = self.repo.get_claims_by_issue(issue_id)
    
        from app.domains.issues.schemas import ClaimCardResponse
        claim_cards = [
            ClaimCardResponse(
                id=c.id,
                press=c.press,
                title=c.article.title if c.article else "",
                claim=c.claim,
                evidence=c.evidence,
                url=c.article.url if c.article else None
            ) for c in claims
        ]
    
        # 3. 이미지 URL 조회
        image_urls = self.repo.get_image_urls_by_issue(issue_id)
    
        return IssueDraftResponse(
            id=issue.id,
            name=issue.name,
            description=issue.description,
            background=issue.background,
            pre_generated_draft=issue.pre_generated_draft,
            issue_type=issue.issue_type,
            created_at=issue.created_at,
            claim_cards=claim_cards,
            image_urls=image_urls
        )

    def recommend_headlines(self, issue_id: int) -> HeadlineRecommendationResponse:
        """초안 텍스트를 바탕으로 LLM(local_only)을 호출하여 제목 5개를 추천받습니다."""
        issue = self.repo.get_by_id(issue_id)
        if not issue or not issue.pre_generated_draft:
            raise HTTPException(status_code=404, detail="해당 이슈의 초안이 존재하지 않습니다.")

        prompt = f"""
다음은 작성된 기사 초안입니다. 이 내용에 가장 잘 어울리고 독자의 시선을 끄는 
기사 헤드라인(제목) 5개를 추천해주세요.

[초안 내용]
{issue.pre_generated_draft}

반드시 ["제목1", "제목2", "제목3", "제목4", "제목5"] 형태의 JSON 문자열 리스트로만 응답하세요. 다른 부연 설명은 하지 마세요.
"""
        # local_only 모드로 강제하여 .env에 설정된 LLM_MODEL_NAME 또는 GEMINI_MODEL_NAME(DeepInfra 환경 등)을 사용하도록 함.
        # utils.py 의 call_llm 은 state dict 안의 llm_mode 를 참조합니다.
        state = {"llm_mode": "local_only"}
        # model_size 파라미터는 여기서는 식별자 목적으로 넘깁니다. (utils.py 에서는 dict lookup 에 쓰이거나 target 식별에 쓰임)
        # 로컬(DeepInfra)을 쓸 때는 API URL이 고정이므로 'local' 을 줍니다.
        result, usage = call_llm(prompt, model_size="local", state=state, schema=None)
        
        # 만약 LLM이 리스트가 아닌 딕셔너리로 반환했을 경우 복구 시도
        headlines = []
        if isinstance(result, list):
            headlines = [str(x) for x in result if isinstance(x, str)]
        elif isinstance(result, dict):
            for k, v in result.items():
                if isinstance(v, list):
                    headlines = [str(x) for x in v if isinstance(x, str)]
                    break

        if not headlines:
            raise HTTPException(status_code=500, detail="LLM 응답에서 제목 리스트를 파싱하지 못했습니다.")

        # 정확히 5개가 넘어가면 자름
        return HeadlineRecommendationResponse(headlines=headlines[:5])

    def get_issue_feed(self, date_str: Optional[str] = None, page: int = 1, page_size: int = 10, issue_type: Optional[str] = None) -> IssueFeedResponse:
        target_date = None
        if date_str:
            try:
                target_date = py_date.fromisoformat(date_str)
            except ValueError:
                raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다. (YYYY-MM-DD)")
        else:
            target_date = (datetime.utcnow() + timedelta(hours=9)).date()

        skip = (page - 1) * page_size
        limit = page_size

        issues = self.repo.get_feed_issues(target_date=target_date, skip=skip, limit=limit, issue_type=issue_type)
        total_count = self.repo.get_feed_issues_count(target_date=target_date, issue_type=issue_type)
        total_pages = (total_count + page_size - 1) // page_size

        issue_ids = [issue.id for issue in issues]
        image_urls_map = self.repo.get_image_urls_by_issue_ids(issue_ids)

        issue_items: List[IssueFeedItem] = []
        for idx, issue in enumerate(issues):
            created_at = issue.created_at
            if hasattr(created_at, 'tzinfo') and created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)

            issue_items.append(IssueFeedItem(
                id=issue.id,
                name=issue.name,
                description=issue.description,
                issue_type=issue.issue_type,
                article_count=issue.total_count,
                rank=skip + idx + 1,
                created_at=created_at,
                image_urls=image_urls_map.get(issue.id, [])
            ))

        return IssueFeedResponse(
            date=target_date.isoformat(),
            issues=issue_items,
            total_count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )

    def get_grouped_issues(self, days: int = 7, issue_type: Optional[str] = None) -> IssueGroupedResponse:
        issues = self.repo.get_issues_by_date_range(days=days, issue_type=issue_type)

        issue_ids = [issue.id for issue in issues]
        image_urls_map = self.repo.get_image_urls_by_issue_ids(issue_ids)

        grouped_data: Dict[str, List[IssueFeedItem]] = defaultdict(list)

        for issue in issues:
            created_at = issue.created_at
            if hasattr(created_at, 'tzinfo') and created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)

            date_key = created_at.date().isoformat()
            rank_in_day = len(grouped_data[date_key]) + 1

            grouped_data[date_key].append(IssueFeedItem(
                id=issue.id,
                name=issue.name,
                description=issue.description,
                issue_type=issue.issue_type,
                article_count=issue.total_count,
                rank=rank_in_day,
                created_at=created_at,
                image_urls=image_urls_map.get(issue.id, [])
            ))

        return IssueGroupedResponse(data=dict(grouped_data))

    def get_issue_timeline(self, issue_id: int):
        """특정 이슈와 타이틀이 유사한 이슈들을 찾고 그 중 과거의 이슈들을 타임라인으로 반환합니다."""
        target_issue = self.repo.get_by_id(issue_id)
        if not target_issue:
            raise HTTPException(status_code=404, detail="해당 이슈를 찾을 수 없습니다.")

        # 최근 이슈 N개 조회 (성능을 위해 제한)
        recent_issues = self.repo.get_recent_issues_for_timeline(limit=400)

        import difflib
        
        # 유사도 필터링
        similar_issues = []
        for issue in recent_issues:
            # 타임라인에는 과거부터 현재까지 발생한 이슈가 포함됩니다.
            # difflib.SequenceMatcher 로 글자 기반 유사도 측정 (한국어 텍스트에 효과적임)
            ratio = difflib.SequenceMatcher(None, target_issue.name, issue.name).ratio()
            
            # 1. 대상 이슈 이름에 부분 문자열이 완전히 포함
            # 2. 혹은 글자 유사도가 55% 이상인 경우 타임라인으로 간주
            if (target_issue.name in issue.name or 
                issue.name in target_issue.name or 
                ratio >= 0.55):
                similar_issues.append(issue)

        # 시간순(과거->최신) 정렬
        similar_issues.sort(key=lambda x: x.created_at)

        # 이미지 URL 일괄 조회
        issue_ids = [iss.id for iss in similar_issues]
        image_urls_map = self.repo.get_image_urls_by_issue_ids(issue_ids)
        
        timeline_items = []
        for issue in similar_issues:
            created_at = issue.created_at
            if hasattr(created_at, 'tzinfo') and created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)
                
            image_urls = image_urls_map.get(issue.id, [])
            
            timeline_items.append(IssueTimelineItem(
                id=issue.id,
                name=issue.name,
                issue_type=issue.issue_type,
                article_count=issue.total_count,
                created_at=created_at,
                image_urls=image_urls,
            ))

        return IssueTimelineResponse(
            target_issue_id=target_issue.id,
            target_issue_name=target_issue.name,
            timeline=timeline_items
        )

    def get_issue_feed_legacy(self, top_count: int = 10, chart_out_count: int = 20) -> IssueFeedLegacyResponse:
        """
        피드용 30개 이슈 조회 (레거시 버전)
        - top_issues     : 가장 최근 생성된 top_count개
        - chart_out_issues: 그 이후 chart_out_count개 (차트아웃 시간 계산 포함)
        """
        total = top_count + chart_out_count
        # repository의 get_feed_issues를 사용하여 날짜 필터 없이 가져옴 (target_date=None)
        issues = self.repo.get_feed_issues(target_date=None, total=total)

        # 랭킹 경계 기준 시각 (10번째 이슈의 시각)
        boundary_time = None
        if len(issues) >= top_count:
            bt = issues[top_count - 1].created_at
            if hasattr(bt, 'tzinfo') and bt.tzinfo is not None:
                bt = bt.replace(tzinfo=None)
            boundary_time = bt

        now = datetime.utcnow() + timedelta(hours=9)
        top_issues: List[IssueFeedLegacyItem] = []
        chart_out_issues: List[IssueFeedLegacyItem] = []

        # 이미지 URL 일괄 조회
        issue_ids = [issue.id for issue in issues]
        image_urls_map = self.repo.get_image_urls_by_issue_ids(issue_ids)

        for idx, issue in enumerate(issues):
            rank_in_feed = idx + 1
            created_at = issue.created_at
            if hasattr(created_at, 'tzinfo') and created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)

            image_urls = image_urls_map.get(issue.id, [])

            if idx < top_count:
                # TOP 이슈 (최신 10개)
                top_issues.append(IssueFeedLegacyItem(
                    id=issue.id,
                    name=issue.name,
                    description=issue.description,
                    issue_type=issue.issue_type,
                    article_count=issue.total_count,
                    rank=rank_in_feed,
                    created_at=created_at,
                    is_chart_out=False,
                    image_urls=image_urls,
                ))
            else:
                # 차트아웃 이슈 (그 다음 20개)
                peak_rank = rank_in_feed
                if boundary_time is not None:
                    diff_minutes = int((boundary_time - created_at).total_seconds() / 60)
                else:
                    diff_minutes = int((now - created_at).total_seconds() / 60)

                chart_out_issues.append(IssueFeedLegacyItem(
                    id=issue.id,
                    name=issue.name,
                    description=issue.description,
                    issue_type=issue.issue_type,
                    article_count=issue.total_count,
                    rank=rank_in_feed,
                    created_at=created_at,
                    is_chart_out=True,
                    peak_rank=peak_rank,
                    chart_out_minutes=max(0, diff_minutes),
                    image_urls=image_urls,
                ))

        return IssueFeedLegacyResponse(
            top_issues=top_issues,
            chart_out_issues=chart_out_issues,
        )

    def delete_issue(self, issue_id: int):
        """이슈 삭제 및 연쇄 데이터 삭제"""
        issue = self.repo.get_by_id(issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="해당 이슈를 찾을 수 없습니다.")
        
        self.repo.delete_issue(issue_id)

