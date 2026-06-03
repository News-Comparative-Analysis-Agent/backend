from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import engine, Base

from app.domains.users import router as users_router
from app.domains.articles import router as articles_router
from app.domains.issues import router as issues_router
from app.domains.drafts.router import router as drafts_router
from tests import db_api as db_test_router
from app.domains.system import router as system_router

# 인증 의존성 임포트
from app.core.security import get_current_user

# SQLAlchemy 모델 로드 및 DB 테이블 생성
from app.domains.users import models as user_models
from app.domains.publishers import models as pub_models
from app.domains.articles import models as art_models
from app.domains.issues import models as issue_models
from app.domains.drafts import models as draft_models
from app.domains.system import models as system_models

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

# 2. 보호된 엔드포인트 (인증 필수) 잠시 주석처리
# protected_dependency = [Depends(get_current_user)]

app.include_router(articles_router.router, prefix="/articles", tags=["articles"])
app.include_router(issues_router.router, prefix="/issues", tags=["issues"])
app.include_router(drafts_router, prefix="/draft", tags=["drafts"])
app.include_router(system_router.router, prefix="/system", tags=["system"])

from app.scroller import router as scroller_router
app.include_router(scroller_router.router, prefix="/scroller", tags=["scroller"])

@app.get("/")
def health_check():
    return {"status": "ok", "message": "백엔드 서버 실행중"}

from fastapi import Request, BackgroundTasks
from fastapi.responses import JSONResponse
import traceback
from app.core.logger import logger
from app.core.email import send_error_email

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_msg = str(exc)
    traceback_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    
    client_host = request.client.host if request.client else 'Unknown'
    request_info = f"URL: {request.url}\nMethod: {request.method}\nClient: {client_host}"
    
    logger.error(f"Unhandled Exception: {error_msg}\n{traceback_str}")

    background_tasks = BackgroundTasks()
    background_tasks.add_task(
        send_error_email,
        error_message=error_msg,
        traceback_str=traceback_str,
        request_info=request_info
    )

    return JSONResponse(
        status_code=500,
        content={"detail": "서버 내부 오류가 발생했습니다. 관리자에게 리포트되었습니다."},
        background=background_tasks
    )

@app.get("/api/test/error", tags=["test"])
def test_error_email():
    """의도적으로 500 에러를 발생시켜 이메일 알림을 테스트합니다."""
    raise ValueError("이메일 발송 테스트용 의도된 에러입니다.")

