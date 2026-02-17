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
    description="Aigent Backend API"
)

# 프론트랑 연결해봐야 할것 같아서 잠만 쓸게 ㅎㅎ
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록 prefix: /users가 자동으로 붙음. tags: API 문서용.
app.include_router(users_router.router, prefix="/user", tags=["users"])
app.include_router(topics_router.router, prefix="/topics", tags=["topics"])
app.include_router(articles_router.router, prefix="/articles", tags=["articles"])
app.include_router(issues_router.router, prefix="/issues", tags=["issues"])
from app.scroller import router as scroller_router
app.include_router(scroller_router.router, prefix="/scroller", tags=["scroller"])
app.include_router(kw_relation_router.router, prefix="/keyword-network", tags=["keyword-network"])

from app.draft import ai_draft
app.include_router(ai_draft.router, prefix="/api/draft", tags=["draft"])

from app.draft import three_perspect
app.include_router(three_perspect.router, prefix="/api/draft", tags=["draft-perspective"])

from app.draft import similarity
app.include_router(similarity.router, prefix="/api/draft", tags=["draft-similarity"])

from app.draft import images
app.include_router(images.router, prefix="/api/draft", tags=["draft-images"])


@app.get("/")
def health_check():
    return {"status": "ok", "message": "백엔드 서버 실행중"}
