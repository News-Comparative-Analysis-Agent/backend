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
    dos2unix \
    && rm -rf /var/lib/apt/lists/*

# 패키지 목록 복사 및 설치 (캐싱 효율화)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 전체 복사
COPY . .

# entrypoint.sh를 볼륨 마운트 영향이 없는 루트 디렉토리로 복사 및 줄바꿈 변환
# (docker-compose의 .:/app 마운트가 윈도우의 CRLF 파일로 덮어쓰는 것을 방지)
RUN cp entrypoint.sh /entrypoint.sh && \
    dos2unix /entrypoint.sh && \
    chmod +x /entrypoint.sh

# 실행 명령어 (루트의 안전한 entrypoint 실행)
ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]
