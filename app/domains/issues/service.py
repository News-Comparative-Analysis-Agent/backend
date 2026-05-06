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
from app.core.logger import logger

# SBERT 모델 싱글톤 (타임라인 후보군 필터링용)
_sbert_model = None

def get_sbert_model():
    """클러스터링과 동일한 한국어 SBERT 모델을 싱글톤으로 로드"""
    global _sbert_model
    if _sbert_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            # 기존 클러스터링(ClusterAgent)에서 사용하는 것과 동일한 고성능 한국어 모델
            _sbert_model = SentenceTransformer("snunlp/KR-SBERT-V40K-klueNLI-augSTS")
            logger.info("✅ [IssueService] Timeline SBERT 모델 로드 완료")
        except Exception as e:
            logger.error(f"❌ [IssueService] SBERT 모델 로드 실패: {e}")
            return None
    return _sbert_model

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
        state = {"llm_mode": "local_only"}
        result, usage = call_llm(prompt, model_size="local", state=state, schema=None)
        
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

    def link_parent_issue(self, new_issue_id: int) -> None:
        """
        새로 생성된 이슈가 기존 이슈의 후속인지 LLM으로 판별하고
        parent_issue_id와 phase를 저장합니다.
        """
        new_issue = self.repo.get_by_id(new_issue_id)
        if not new_issue:
            logger.warning(f"[Timeline] 이슈 {new_issue_id} 없음, 건너뜀")
            return
     
        # 1. 일단 넓게 후보군을 가져옵니다 (최근 60일치 중 최대 200개)
        all_candidates = self.repo.get_recent_issues_for_linkage(days=60, exclude_id=new_issue_id, limit=200)
     
        if not all_candidates:
            # 후보 없으면 자기 자신이 루트
            self.repo.update_issue_linkage(new_issue_id, parent_issue_id=new_issue_id, phase="발생")
            logger.info(f"[Timeline] 이슈 {new_issue_id} → 후보 없음, 독립 루트로 설정")
            return

        # 2. SBERT를 이용해 의미적으로 유사한 상위 20개만 선별 (토큰 최적화)
        candidates = self._filter_candidates_by_similarity(new_issue, all_candidates, top_k=20)
     
        # 후보군 텍스트 구성
        candidate_texts = "\n".join([
            f"[ID:{c.id}] 제목: {c.name}\n갈등구도: {c.conflict_summary or '없음'}\n생성일: {c.created_at.strftime('%m.%d')}"
            for c in candidates
        ])
     
        prompt = f"""
당신은 뉴스 이슈의 연속성을 판별하는 전문가입니다.
 
[새로 생성된 이슈]
제목: {new_issue.name}
갈등구도: {new_issue.conflict_summary or '없음'}
배경: {new_issue.background or '없음'}
 
[기존 이슈 후보군 (최근 2개월, 루트 이슈들)]
{candidate_texts}
 
판단 기준:
- 동일한 사건/의혹의 후속 보도라면 → 해당 이슈 ID 반환
- 인물이나 키워드가 겹쳐도 사건 자체가 다르면 → null 반환
- 확실하지 않으면 → null 반환 (새 루트로 시작하는 게 안전)
 
phase 기준:
- 발생: 사건이 처음 알려진 단계
- 확산: 여러 언론/진영으로 반응이 퍼지는 단계
- 대응: 관련 당사자들이 공식 입장을 내는 단계
- 교착: 입장 차가 좁혀지지 않고 교착 상태
- 해소: 결론이 나거나 사건이 일단락된 단계
 
반드시 아래 JSON 형식으로만 응답하세요:
{{
    "parent_issue_id": 123 또는 null,
    "phase": "발생/확산/대응/교착/해소 중 하나",
    "reason": "판단 근거 한 줄"
}}
"""
     
        try:
            from app.scroller.repository import ScrollerRepository
            scroller_repo = ScrollerRepository(self.db)
            settings = scroller_repo.get_system_settings()
            llm_mode = settings.llm_mode if settings else "local_only"
            
            result, _ = call_llm(prompt=prompt, model_size="local", state={"llm_mode": llm_mode})
     
            if not result:
                raise ValueError("LLM 응답 없음")
     
            parent_id = result.get("parent_issue_id")
            phase = result.get("phase", "발생")
            reason = result.get("reason", "")
     
            valid_ids = {c.id for c in candidates}
            if parent_id and parent_id not in valid_ids:
                logger.warning(f"[Timeline] LLM이 반환한 parent_id={parent_id}가 후보군에 없음 → 독립 루트로 설정")
                parent_id = None
     
            final_parent_id = parent_id if parent_id else new_issue_id
     
            self.repo.update_issue_linkage(
                issue_id=new_issue_id,
                parent_issue_id=final_parent_id,
                phase=phase
            )
     
            if parent_id:
                logger.info(f"[Timeline] 이슈 {new_issue_id} → 루트 {parent_id}의 후속 ({phase}) | {reason}")
            else:
                logger.info(f"[Timeline] 이슈 {new_issue_id} → 독립 루트 ({phase}) | {reason}")
     
        except Exception as e:
            logger.error(f"[Timeline] link_parent_issue 실패 (issue_id={new_issue_id}): {e}")
            self.repo.update_issue_linkage(new_issue_id, parent_issue_id=new_issue_id, phase="발생")

    def get_issue_timeline(self, issue_id: int):
        from app.domains.issues.schemas import IssueTimelineItem, IssueTimelineResponse
     
        issue = self.repo.get_by_id(issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="해당 이슈를 찾을 수 없습니다.")
     
        root_id = self.repo.get_root_issue_id(issue_id)
        timeline_issues = self.repo.get_timeline_by_root(root_id)
     
        issue_ids = [iss.id for iss in timeline_issues]
        image_urls_map = self.repo.get_image_urls_by_issue_ids(issue_ids)
     
        timeline_items = []
        for iss in timeline_issues:
            created_at = iss.created_at
            if hasattr(created_at, 'tzinfo') and created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)
     
            timeline_items.append(IssueTimelineItem(
                id=iss.id,
                name=iss.name,
                phase=iss.phase,
                issue_type=iss.issue_type,
                conflict_summary=iss.conflict_summary,
                article_count=iss.total_count,
                created_at=created_at,
                image_urls=image_urls_map.get(iss.id, []),
            ))
     
        return IssueTimelineResponse(
            target_issue_id=issue_id,
            target_issue_name=issue.name,
            root_issue_id=root_id,
            timeline=timeline_items
        )

    def get_issue_feed_legacy(self, top_count: int = 10, chart_out_count: int = 20) -> IssueFeedLegacyResponse:
        total = top_count + chart_out_count
        issues = self.repo.get_feed_issues(target_date=None, total=total)

        boundary_time = None
        if len(issues) >= top_count:
            bt = issues[top_count - 1].created_at
            if hasattr(bt, 'tzinfo') and bt.tzinfo is not None:
                bt = bt.replace(tzinfo=None)
            boundary_time = bt

        now = datetime.utcnow() + timedelta(hours=9)
        top_issues: List[IssueFeedLegacyItem] = []
        chart_out_issues: List[IssueFeedLegacyItem] = []

        issue_ids = [issue.id for issue in issues]
        image_urls_map = self.repo.get_image_urls_by_issue_ids(issue_ids)

        for idx, issue in enumerate(issues):
            rank_in_feed = idx + 1
            created_at = issue.created_at
            if hasattr(created_at, 'tzinfo') and created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)

            image_urls = image_urls_map.get(issue.id, [])

            if idx < top_count:
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
        issue = self.repo.get_by_id(issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="해당 이슈를 찾을 수 없습니다.")
        self.repo.delete_issue(issue_id)

    def _filter_candidates_by_similarity(self, target_issue, candidates, top_k=20):
        """Sentence-BERT 임베딩을 이용해 의미적으로 가장 유사한 후보 이슈들을 선별합니다."""
        try:
            from sklearn.metrics.pairwise import cosine_similarity
            import numpy as np
            
            model = get_sbert_model()
            if model is None:
                raise ValueError("SBERT 모델을 사용할 수 없습니다.")

            # 비교 텍스트 생성 (제목 + 배경)
            target_text = f"{target_issue.name} {target_issue.background or ''}"
            candidate_texts = [f"{c.name} {c.background or ''}" for c in candidates]

            # SBERT 벡터화 (의미 파악)
            target_emb = model.encode([target_text], show_progress_bar=False)
            candidate_embs = model.encode(candidate_texts, show_progress_bar=False)
            
            # 코사인 유사도 계산
            cosine_sim = cosine_similarity(target_emb, candidate_embs).flatten()

            # 유사도 높은 순으로 인덱스 정렬
            top_indices = np.argsort(cosine_sim)[-top_k:][::-1]
            
            selected = [candidates[i] for i in top_indices]
            logger.info(f"🧠 [Timeline:SBERT] {len(candidates)}개 후보 중 의미 유사도 상위 {len(selected)}개 선별 완료")
            return selected
            
        except Exception as e:
            logger.warning(f"⚠️ [Timeline:SBERT] 유사도 필터링 실패, 최신순으로 대체합니다: {e}")
            return candidates[:top_k]
