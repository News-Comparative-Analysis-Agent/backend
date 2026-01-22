from fastapi import FastAPI
from app.core.config import settings

app = FastAPI(
    title="Aigent Backend API",
    version="1.0.0",
    description="Aigent Backend API"
)

@app.get("/")
def health_check():
    return {"status": "ok", "message": "백엔드 서버 실행중"}
