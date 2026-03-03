from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from app.core.database import get_db
from app.domains.drafts.schemas import (
    StreamDraftRequest, ChatRequest, ChatResponse, ImageItem, 
    SimilarityRequest, SimilarityResponse,
    PerspectivesResponse
)
from app.domains.drafts.service import DraftService

router = APIRouter()

# 1. 자동 초안 스트리밍 생성 API
@router.post("/ai_draft/stream", summary="비평 기사 자동 생성 (스트리밍)")
async def generate_draft_stream_api(request: StreamDraftRequest, db: Session = Depends(get_db)):
    """
    특정 이슈(issue_id)와 관련된 기사들을 바탕으로, 비평 기사 초안을 스트리밍 방식으로 생성합니다.
    """
    service = DraftService(db)
    return service.generate_draft_stream(request.issue_id)

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
    """
    service = DraftService(db)
    return service.get_issue_images(issue_id)

# 4. 표절 유사도 검사 API
@router.post("/similarity", response_model=SimilarityResponse, summary="기사 유사도 검사")
async def check_similarity_api(request: SimilarityRequest, db: Session = Depends(get_db)):
    """
    작성된 기사 초안과 해당 이슈의 기존 기사들의 텍스트 겹침 정도를 비교하여 % 점수로 알려줍니다.
    """
    service = DraftService(db)
    return service.check_similarity(request)

# 5. 3가지 진영 관점 분석 API
@router.get("/perspectives/{issue_id}", response_model=PerspectivesResponse, summary="진보/중립/보수 관점 기사 분석")
async def analyze_perspectives_api(issue_id: int, db: Session = Depends(get_db)):
    """
    해당 이슈의 기사들을 언론사 성향(보수/진보/중립)별로 3그룹으로 나눈 후, 
    Gemini를 통해 각 진영의 논점을 요약 분석하여 반환합니다.
    """
    service = DraftService(db)
    return await service.analyze_perspectives(issue_id)

# 6. 초안 작업실 가져오기 API
@router.post("/workspace/from-issue", summary="시스템 초안을 내 작업실로 가져오기")
async def save_draft_to_workspace_api(
    request: SaveDraftRequest, 
    db: Session = Depends(get_db)
    # user: User = Depends(get_current_user) # 추후 사용자 인증 활성화 시 주석 해제하여 사용
):
    """
    이슈의 pre_generated_draft를 읽어서 현재 로그인한 유저의 Draft 테이블로 복사(저장)합니다.
    (현재 인증이 임시 비활성화 상태라 임의의 user_id 1번을 사용합니다 - 추후 get_current_user 연동)
    """
    service = DraftService(db)
    user_id = 1 # FIXME: 추후 인증 미들웨어가 활성화되면 user.id 로 변경
    
    new_draft_id = service.save_issue_draft_to_workspace(user_id=user_id, request=request)
    
    # SaveDraftResponse 스키마 리턴 대신 임시 딕셔너리 또는 스키마 매핑
    return {"message": "초안이 작업실에 성공적으로 저장되었습니다.", "draft_id": new_draft_id}
