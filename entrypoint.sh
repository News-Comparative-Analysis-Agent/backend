#!/bin/bash
# 자동 마이그레이션 ORM코드와 DB를 연동하는 파일

# DB가 준비될 때까지 잠시 대기
echo "데이터베이스가 준비될 때까지 대기 중..."
sleep 3

# 최신 마이그레이션 적용 (DB 구조 업데이트)
echo "데이터베이스 마이그레이션 실행 중..."
if alembic upgrade head; then
    echo "마이그레이션이 성공적으로 완료되었습니다."
else
    echo "마이그레이션에 실패했으나, 서버 실행을 계속합니다..."
fi

# 애플리케이션 서버 실행
echo "FastAPI 서버를 시작합니다..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
