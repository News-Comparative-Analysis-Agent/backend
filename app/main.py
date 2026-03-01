from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import engine, Base

from app.domains.users import router as users_router
from app.domains.articles import router as articles_router
from app.domains.issues import router as issues_router
from app.scroller import router as scroller_router
from app.domains.drafts.router import router as drafts_router
from tests import db_api as db_test_router

# 인증 의존성 임포트
from app.core.security import get_current_user

# SQLAlchemy 모델 로드
from app.domains.users import models as user_models
from app.domains.publishers import models as pub_models
from app.domains.articles import models as art_models
from app.domains.issues import models as issue_models
from app.domains.drafts import models as draft_models

# DB 테이블 생성
Base.metadata.create_all(bind=engine)

app = FastAPI(description="Aigent Backend API")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. 공개 엔드포인트 (로그인 등)
app.include_router(users_router.router, prefix="/user", tags=["users"])
app.include_router(db_test_router.router, prefix="/api/test/db", tags=["test"])

# 2. 보호된 엔드포인트 (인증 필수)
protected_dependency = [Depends(get_current_user)]

app.include_router(articles_router.router, prefix="/articles", tags=["articles"], dependencies=protected_dependency)
app.include_router(issues_router.router, prefix="/issues", tags=["issues"], dependencies=protected_dependency)
app.include_router(scroller_router.router, prefix="/scroller", tags=["scroller"], dependencies=protected_dependency)
app.include_router(drafts_router, prefix="/api/draft", tags=["drafts"], dependencies=protected_dependency)

@app.get("/")
def health_check():
    return {"status": "ok", "message": "백엔드 서버 실행중"}
