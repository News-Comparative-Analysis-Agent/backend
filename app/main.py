from fastapi import FastAPI
from app.core.config import settings
from app.domains.users import router as users_router
from app.domains.topics import router as topics_router
from app.domains.articles import router as articles_router
from app.domains.issues import router as issues_router
from app.domains.keywordrelation import router as kw_relation_router

# SQLAlchemy 모델 로드 (관계 설정을 위해 모든 모델이 레지스트리에 등록되어야 함)
from app.domains.users import models
from app.domains.topics import models
from app.domains.publishers import models
from app.domains.articles import models
from app.domains.issues import models
from app.domains.keywordrelation import models
from app.domains.drafts import models

app = FastAPI(
    title="Aigent Backend API",
    version="1.0.0",
    description="Aigent Backend API"
)

# 라우터 등록 prefix: /users가 자동으로 붙음. tags: API 문서용.
app.include_router(users_router.router, prefix="/user", tags=["users"])
app.include_router(topics_router.router, prefix="/topics", tags=["topics"])
app.include_router(articles_router.router, prefix="/articles", tags=["articles"])
app.include_router(issues_router.router, prefix="/issues", tags=["issues"])
app.include_router(kw_relation_router.router, prefix="/keyword-network", tags=["keyword-network"])

@app.get("/")
def health_check():
    return {"status": "ok", "message": "백엔드 서버 실행중"}
