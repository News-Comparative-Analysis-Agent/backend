from fastapi import FastAPI
from app.core.config import settings
from app.domains.users import router as users_router
from app.domains.topics import router as topics_router
from app.domains.articles import router as articles_router

app = FastAPI(
    title="Aigent Backend API",
    version="1.0.0",
    description="Aigent Backend API"
)

# 라우터 등록 prefix: /users가 자동으로 붙음. tags: API 문서용.
app.include_router(users_router.router, prefix="/user", tags=["users"])

@app.get("/")
def health_check():
    return {"status": "ok", "message": "백엔드 서버 실행중"}
