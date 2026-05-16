import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()
db_url = os.getenv("DATABASE_URL")

engine = create_engine(
    db_url,
    connect_args={"options": "-c client_encoding=UTF8"},
    pool_size=20,          # 기본 연결 수 확대
    max_overflow=10,       # 최대 초과 허용 수
    pool_recycle=3600,     # 연결 재사용 주기 (1시간)
    pool_pre_ping=True     # 연결 유효성 체크 활성화
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
