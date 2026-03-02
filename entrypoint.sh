#!/bin/bash
# 자동 마이그레이션 ORM코드와 DB를 연동하는 파일

# DB가 준비될 때까지 잠시 대기 (선택 사항이지만 권장됨)
echo "Waiting for database to be ready..."
sleep 3

# 최신 마이그레이션 적용 (DB 구조 업데이트)
echo "Running database migrations..."
alembic upgrade head

# 애플리케이션 서버 실행
echo "Starting FastAPI server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
