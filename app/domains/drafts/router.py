from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from app.core.database import get_db
from app.domains.drafts.schemas import (
    StreamDraftRequest, ChatRequest, ChatResponse, ImageItem, 
    SimilarityRequest, SimilarityResponse,
    PerspectivesResponse, SaveDraftRequest,
    FinalReviewResponse, DraftUpdate
)
from app.domains.drafts.service import DraftService
from app.domains.users.models import User
from app.core.security import get_current_user

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


@router.post("/workspace/from-issue", summary="시스템 초안을 내 작업실로 가져오기")
async def save_draft_to_workspace_api(
    request: SaveDraftRequest, 
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    이슈의 pre_generated_draft를 읽어서 현재 로그인한 유저의 Draft 테이블로 복사(저장)합니다.
    """
    service = DraftService(db)
    new_draft_id = service.save_issue_draft_to_workspace(user_id=user.id, request=request)
    
    return {"message": "초안이 작업실에 성공적으로 저장되었습니다.", "issue_id": new_draft_id}

@router.put("/issue/{issue_id}", summary="초안 수정 및 임시 저장 (이슈 기준)")
async def update_draft_api(
    issue_id: int,
    request: DraftUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """이슈 ID를 기준으로 초안 본문 내용을 업데이트합니다."""
    service = DraftService(db)
    updated_id = service.update_issue_draft(issue_id, request.content, user.id)
    return {"message": "초안이 성공적으로 수정되었습니다.", "issue_id": updated_id}

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
