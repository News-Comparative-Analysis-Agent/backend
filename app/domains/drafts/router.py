from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from app.core.database import get_db
from app.domains.users.service import UserService
from app.domains.users.schemas import TokenResponse, MyPageResponse, MyPageDraftSummary
from app.domains.drafts.schemas import (
    StreamDraftRequest, ChatRequest, ChatResponse, ImageItem,
    FinalReviewResponse, SimilarityRequest, SimilarityResponse, 
    PerspectivesResponse, WorkspaceDraftSummary, DraftUpdate,
    DraftWithCitationsResponse, ArticleBodyResponse
)
from app.domains.drafts.service import DraftService
router = APIRouter()

# 2. AI 챗봇 대화 및 수정 API
@router.post("/chat", response_model=ChatResponse, summary="초안 첨삭 및 작성 보조 챗봇")
async def chat_with_ai_api(request: ChatRequest, db: Session = Depends(get_db)):
    """
    기사 수정을 도와주는 AI와의 챗봇 엔드포인트입니다.
    질의응답 및 초안 직접 텍스트 수정이 가능합니다.
    """
    service = DraftService(db)
    return service.chat_with_ai(request)

# 3. 이미지 조회 API
@router.get("/images/{issue_id}", response_model=List[ImageItem], summary="관련 이미지 목록 조회")
async def get_issue_images_api(issue_id: int, db: Session = Depends(get_db)):
    """
    특정 이슈 ID에 묶인 기사들에 포함된 대표 이미지 URL들을 중복 없이 반환합니다.
    (기존 DB 항목 외에, 각 기사 페이지에서 동적으로 이미지를 추가 추출합니다)
    """
    service = DraftService(db)
    return await service.get_issue_images(issue_id)


@router.get("/workspace", response_model=List[WorkspaceDraftSummary], summary="내 작업실 초안 목록 조회")
async def get_workspace_drafts_api(
    db: Session = Depends(get_db)
):
    """현재 로그인한 유저의 작업실에 보관된 모든 초안 목록을 반환합니다."""
    service = DraftService(db)
    return service.get_user_workspace_drafts(user_id=1)

@router.put("/issue/{issue_id}", summary="초안 수정 및 임시 저장 (이슈 기준)")
async def update_draft_api(
    issue_id: int,
    request: DraftUpdate,
    db: Session = Depends(get_db)
):
    """
    이슈 ID를 기준으로 초안 본문 내용을 업데이트하고, 
    해당 이슈를 사용자의 작업실 목록에 추가합니다. (임시 저장 및 목록 추가 동시 수행)
    """
    service = DraftService(db)
    updated_id = service.update_issue_draft(issue_id, request.content, user_id=1)
    
    return {"message": "초안이 성공적으로 수정 및 저장되었습니다.", "issue_id": updated_id}


# 7. 최종 품질 검토 API
@router.get("/final-review/{issue_id}", response_model=FinalReviewResponse, summary="최종 품질 검토 리포트 생성")
async def final_review_api(issue_id: int, db: Session = Depends(get_db)):
    """
    사용자가 수정한 최종 기사(user_content)를 AI가 검토하여 품질 리포트를 반환합니다. (LangGraph 기반)
    
    - **reliability**: 원본 기사 대비 유사도 점수 + 소스 기사 3건
    - **guideline_checks**: 차별 표현, 자극적 형용사, 낙인화 표현, 미확인 사실 등 4가지 가이드라인 검증
    - **ai_opinion**: AI 에이전트의 최종 종합 의견
    """
    service = DraftService(db)
    return await service.run_final_review(issue_id)


# 8. Citation (인용 출처) 조회 API
@router.get(
    "/citations/{issue_id}",
    response_model=DraftWithCitationsResponse,
    summary="기사 초안 인용 출처 조회",
    description="""
저장된 기사 초안 본문에 언론사별 인용 마커 [N]을 삽입하고,
각 마커에 대응하는 원문 출처 정보(언론사, 제목, URL, 전체 evidence)를 반환합니다.

프론트엔드에서 [N] 마커를 클릭하면 citations[N] 데이터를 팝업으로 표시하여
할루시네이션 없이 원문에서 그대로 인용했음을 증명할 수 있습니다.
"""
)
def get_draft_citations(issue_id: int, db: Session = Depends(get_db)):
    """
    [N] 마커가 삽입된 기사 본문 + 언론사별 citation 배열 반환.
    DB의 ArticleClaim 테이블을 조회하여 실시간으로 생성합니다. (LLM 미사용)
    """
    service = DraftService(db)
    return service.get_draft_with_citations(issue_id)


# 9. 기사 원문 lazy-load API
@router.get("/article-body/{article_id}", response_model=ArticleBodyResponse, summary="기사 원문 조회 (인용 팝업용)")
async def get_article_body_api(article_id: int, db: Session = Depends(get_db)):
    """
    인용 마커 클릭 시 팝업에 표시할 기사 원문을 반환합니다.
    응답 크기를 줄이기 위해 citations API와 분리하여 lazy-load 방식으로 호출합니다.
    """
    service = DraftService(db)
    raw_content = service.get_article_body(article_id)
    if raw_content is None:
        raise HTTPException(status_code=404, detail="기사 원문을 찾을 수 없습니다.")
    return ArticleBodyResponse(article_id=article_id, raw_content=raw_content)

