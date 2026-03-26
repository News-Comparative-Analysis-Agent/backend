import os
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from app.core.database import get_db
from app.domains.users.models import User
from app.domains.users.service import UserService
from app.domains.users.schemas import TokenResponse, MyPageResponse, MyPageDraftSummary
from app.core.security import create_access_token, get_current_user
from app.domains.issues.models import IssueLabel


router = APIRouter()

# .env 로드
load_dotenv()

@router.get("/login/kakao")
async def login_kakao(code: str, db: Session = Depends(get_db)):
    """
    카카오 OAuth 로그인 콜백 엔드포인트
    - 인가 코드를 받아 카카오 토큰 및 유저 정보를 획득하고 통합 로그인을 처리합니다.
    """
    # 환경 변수 직접 로드
    CLIENT_ID = os.getenv("KAKAO_CLIENT_ID", "").strip().strip('"').strip("'")
    REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI", "").strip().strip('"').strip("'")
    
    if not CLIENT_ID or not REDIRECT_URI:
        raise HTTPException(status_code=500, detail="카카오 OAuth 설정이 누락되었습니다.")

    service = UserService(db)
    try:
        print("라우터 진입 code: ", code)
        # 1. 액세스 토큰 획득
        access_token = await service.get_kakao_access_token(code, CLIENT_ID, REDIRECT_URI)
        # 2. 유저 정보 획득
        kakao_info = await service.get_kakao_user_info(access_token)
        
        email = kakao_info.get("kakao_account", {}).get("email")
        provider_id = str(kakao_info.get("id"))
        nickname = kakao_info.get("properties", {}).get("nickname")
        
        print("email: ", email)
        print("provider_id: ", provider_id)
        print("nickname: ", nickname)
        if not email:
            raise HTTPException(status_code=400, detail="카카오 이메일 동의가 필요합니다.")

        # 3. 통합 로그인 처리 (이메일이 같으면 기존 계정에 연결됨)
        user = service.social_login(email, "kakao", provider_id, nickname)
        
        # 4. JWT 발행
        jwt_token = create_access_token(subject=user.id)
        print("jwt_token: ", jwt_token)
        return {
            "access_token": jwt_token,
            "token_type": "bearer",
            "user": user
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/me", response_model=MyPageResponse, summary="내 정보 및 초안 목록 & 스크랩한 기사들 조회 (마이페이지)")
async def get_my_page(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    현재 로그인한 사용자의 프로필 정보와 작성 중인 초안 목록을 반환합니다.
    """
    from datetime import datetime
    # draft_issue_ids가 있다면 해당 이슈 정보들을 가져오기
    drafts = []
    if user.draft_issue_ids:
        # DB에서 해당 이슈들 조회
        issues = db.query(IssueLabel).filter(IssueLabel.id.in_(user.draft_issue_ids)).all()
        for issue in issues:
            drafts.append(MyPageDraftSummary(
                issue_id=issue.id,
                title=issue.name,
                updated_at=getattr(issue, "created_at", datetime.now()) 
            ))

    return MyPageResponse(
        user=user,
        drafts=drafts
    )

@router.get("/login/google", response_model=TokenResponse)
async def google_login(id_token: str, db: Session = Depends(get_db)):
    """
    구글 OAuth 로그인 API
    - 프론트엔드에서 전달받은 구글 ID 토큰을 검증하고 통합 로그인을 수행합니다.
    """
    service = UserService(db)
    try:
        print("구글 로그인 api 진입 --- id_token: ", id_token)
        # 1. 구글 토큰 검증
        google_info = await service.verify_google_token(id_token)
        
        email = google_info.get("email")
        provider_id = google_info.get("sub") # 구글의 고유 고정 ID
        nickname = google_info.get("name")
        print("email: ", email)
        print("provider_id: ", provider_id)
        print("nickname: ", nickname)
        if not email:
            raise HTTPException(status_code=400, detail="구글 이메일 정보가 필요합니다.")

        # 2. 통합 로그인 처리
        user = service.social_login(email, "google", provider_id, nickname)
        
        # 3. JWT 발행
        jwt_token = create_access_token(subject=user.id)
        
        return {
            "access_token": jwt_token,
            "token_type": "bearer",
            "user": user
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/llm-mode")
async def get_llm_mode(db: Session = Depends(get_db)):
    """
    현재 플랫폼의 시스템 전역 LLM 작동 모드를 조회합니다.
    (gemini_only, local_priority, local_only 등)
    """
    from app.domains.system.models import SystemSettings
    settings = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    return {"llm_mode": settings.llm_mode if settings else "gemini_only"}