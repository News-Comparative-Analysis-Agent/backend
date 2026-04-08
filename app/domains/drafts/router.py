from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from app.core.database import get_db
from app.domains.users.service import UserService
from app.domains.users.schemas import TokenResponse, MyPageResponse, MyPageDraftSummary
from app.domains.drafts.schemas import (
    StreamDraftRequest, ChatRequest, ChatResponse, ImageItem,
    FinalReviewResponse, SimilarityRequest, SimilarityResponse, 
    PerspectivesResponse, WorkspaceDraftSummary, DraftUpdate
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
