# Python 3.11 Slim 이미지 사용 (가볍고 안정적)
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 의존성 설치 (PostgreSQL 어댑터 빌드용 gcc 등)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 패키지 목록 복사 및 설치 (캐싱 효율화)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 전체 복사
COPY . .

# 실행 명령어 (개발 모드: --reload)
# 주의: 실제로 실행하려면 app/main.py가 존재해야 합니다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
