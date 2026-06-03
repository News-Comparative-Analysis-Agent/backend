#!/bin/bash
# 자동 마이그레이션 ORM코드와 DB를 연동하는 파일

# DB가 준비될 때까지 안전하게 대기 (최대 30초)
echo "데이터베이스가 준비될 때까지 대기 중..."
for i in {1..10}; do
    # 파이썬으로 실제 접속 테스트를 수행하여 복구 모드가 끝났는지 확인
    if python -c "import psycopg2, os; psycopg2.connect(os.getenv('DATABASE_URL'))" 2>/dev/null; then
        echo "데이터베이스 접속 성공! (복구 완료)"
        break
    fi
    echo "데이터베이스 부팅 및 복구 대기 중... ($i/10)"
    sleep 3
done

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
