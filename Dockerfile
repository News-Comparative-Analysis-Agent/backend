# Python 3.11 Slim 이미지 사용 (가볍고 안정적)
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 의존성 설치 (PostgreSQL 어댑터 빌드용 gcc 등)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    default-jdk \
    default-jre \
    && rm -rf /var/lib/apt/lists/*

# 패키지 목록 복사 및 설치 (캐싱 효율화)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 전체 복사 (entrypoint.sh 포함)
COPY . .

# entrypoint.sh에 실행 권한 부여
RUN chmod +x /app/entrypoint.sh

# 실행 명령어 (sh를 통해 실행하여 권한 문제 방지)
ENTRYPOINT ["sh", "/app/entrypoint.sh"]
