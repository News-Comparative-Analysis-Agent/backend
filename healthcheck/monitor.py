#!/usr/bin/env python3
import os
import urllib.request
import urllib.error
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import shutil
import time

# 설정
TARGET_URL = "http://localhost:8000/"  # 헬스체크용 루트 엔드포인트
DISK_USAGE_THRESHOLD = 50  # 디스크 사용량 경고 임계치 (%)
CPU_USAGE_THRESHOLD = 50   # CPU 사용량 경고 임계치 (%)
RAM_USAGE_THRESHOLD = 50   # RAM 사용량 경고 임계치 (%)
ENV_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')

def load_env():
    """간단한 .env 파서 (외부 라이브러리 의존성 제거)"""
    env_vars = {}
    if not os.path.exists(ENV_FILE_PATH):
        return env_vars
    with open(ENV_FILE_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                env_vars[key.strip()] = val.strip().strip('"').strip("'")
    return env_vars

def send_alert_email(subject, body, env_vars):
    """SMTP를 통한 이메일 발송"""
    smtp_server = env_vars.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(env_vars.get("SMTP_PORT", 587))
    smtp_user = env_vars.get("SMTP_USER")
    smtp_password = env_vars.get("SMTP_PASSWORD")
    developer_email = env_vars.get("DEVELOPER_EMAIL")

    if not all([smtp_user, smtp_password, developer_email]):
        print("SMTP 정보가 설정되지 않아 메일을 보낼 수 없습니다.")
        return

    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = developer_email
    msg['Subject'] = subject

    html_body = f"""
    <div style="font-family: sans-serif; padding: 20px;">
        <h2 style="color: #d9534f;">🚨 서버 모니터링 경고 알림</h2>
        <div style="background-color: #f9f9f9; padding: 15px; border-left: 5px solid #d9534f;">
            <p><strong>발생 시간:</strong> {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><strong>경고 내용:</strong></p>
            <pre style="white-space: pre-wrap; color: #333; font-size: 14px;">{body}</pre>
        </div>
    </div>
    """
    msg.attach(MIMEText(html_body, 'html'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        print(f"경고 메일 발송 성공: {subject}")
    except Exception as e:
        print(f"메일 발송 실패: {e}")

def check_api_health():
    """FastAPI 서버 응답 체크"""
    try:
        response = urllib.request.urlopen(TARGET_URL, timeout=10)
        if response.getcode() != 200:
            return False, f"서버가 비정상 상태 코드를 반환했습니다: {response.getcode()}"
        return True, "정상"
    except urllib.error.URLError as e:
        return False, f"서버 접속 실패 (서버 다운 의심): {e.reason}"
    except Exception as e:
        return False, f"예기치 않은 에러: {str(e)}"

def check_disk_usage():
    """디스크 용량 체크"""
    total, used, free = shutil.disk_usage("/")
    percent_used = (used / total) * 100
    if percent_used >= DISK_USAGE_THRESHOLD:
        return False, f"디스크 용량 위험: {percent_used:.1f}% 사용중 (임계치: {DISK_USAGE_THRESHOLD}%)"
    return True, f"디스크 {percent_used:.1f}% 사용중"

def check_cpu_usage():
    """CPU 사용량 체크 (Linux 특화)"""
    try:
        import sys
        if not sys.platform.startswith('linux'):
            return True, "CPU 체크 스킵 (비 리눅스 환경)"
        
        with open('/proc/stat', 'r') as f:
            line1 = f.readline()
        parts1 = [int(i) for i in line1.split()[1:]]
        idle1 = parts1[3] + parts1[4]
        total1 = sum(parts1)
        
        time.sleep(0.5)
        
        with open('/proc/stat', 'r') as f:
            line2 = f.readline()
        parts2 = [int(i) for i in line2.split()[1:]]
        idle2 = parts2[3] + parts2[4]
        total2 = sum(parts2)
        
        total_delta = total2 - total1
        idle_delta = idle2 - idle1
        usage = 100.0 * (1.0 - idle_delta / total_delta) if total_delta > 0 else 0
        
        if usage >= CPU_USAGE_THRESHOLD:
            return False, f"CPU 사용량 위험: {usage:.1f}% 사용중 (임계치: {CPU_USAGE_THRESHOLD}%)"
        return True, f"CPU {usage:.1f}% 사용중"
    except Exception as e:
        return True, f"CPU 체크 실패 (무시됨): {e}"

def check_ram_usage():
    """RAM 사용량 체크 (Linux 특화)"""
    try:
        import sys
        if not sys.platform.startswith('linux'):
            return True, "RAM 체크 스킵 (비 리눅스 환경)"
            
        meminfo = {}
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                parts = line.split(':')
                if len(parts) == 2:
                    meminfo[parts[0]] = int(parts[1].split()[0])
        total = meminfo.get('MemTotal', 1)
        available = meminfo.get('MemAvailable', meminfo.get('MemFree', 0))
        used = total - available
        usage = (used / total) * 100
        
        if usage >= RAM_USAGE_THRESHOLD:
            return False, f"메모리 사용량 위험: {usage:.1f}% 사용중 (임계치: {RAM_USAGE_THRESHOLD}%)"
        return True, f"메모리 {usage:.1f}% 사용중"
    except Exception as e:
        return True, f"RAM 체크 실패 (무시됨): {e}"

def check_docker_containers():
    """주요 Docker 컨테이너 생존 여부 체크"""
    import subprocess
    containers_to_check = ['api_server', 'db_server', 'caddy']
    failed_containers = []
    
    for container in containers_to_check:
        try:
            # docker inspect로 컨테이너 실행 상태(true/false) 확인
            result = subprocess.run(
                ['docker', 'inspect', '-f', '{{.State.Running}}', container],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            # 명령어 자체가 실패했거나 (컨테이너 없음), 실행 상태가 false인 경우
            if result.returncode != 0 or result.stdout.strip() != 'true':
                failed_containers.append(container)
        except Exception as e:
            return False, f"도커 상태 체크 실패 (도커 데몬 확인 필요): {e}"
            
    if failed_containers:
        return False, f"다음 컨테이너가 중지되었습니다: {', '.join(failed_containers)}"
    return True, "모든 도커 컨테이너 정상 실행중"

def main():
    env_vars = load_env()
    alerts = []

    # 1. 도커 컨테이너 헬스체크
    docker_ok, docker_msg = check_docker_containers()
    if not docker_ok:
        alerts.append(f"🐳 [Docker 장애]\n{docker_msg}")

    # 2. API 서버 헬스체크
    api_ok, api_msg = check_api_health()
    if not api_ok:
        alerts.append(f"❌ [API 서버 장애]\n{api_msg}")

    # 3. 인프라 체크 (디스크, CPU, RAM)
    disk_ok, disk_msg = check_disk_usage()
    if not disk_ok:
        alerts.append(f"⚠️ [디스크 경고]\n{disk_msg}")
        
    cpu_ok, cpu_msg = check_cpu_usage()
    if not cpu_ok:
        alerts.append(f"🔥 [CPU 경고]\n{cpu_msg}")
        
    ram_ok, ram_msg = check_ram_usage()
    if not ram_ok:
        alerts.append(f"🔥 [메모리 경고]\n{ram_msg}")

    # 문제가 있다면 메일 발송
    if alerts:
        subject = "🚨 [긴급] Aigent 서버 이상 감지 알림"
        body = "\n\n".join(alerts)
        print("서버 이상 감지! 메일 발송 시도...")
        send_alert_email(subject, body, env_vars)
    else:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 서버 상태 정상")

if __name__ == "__main__":
    main()
