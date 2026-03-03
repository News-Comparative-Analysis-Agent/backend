import sys
import os
from loguru import logger

# 로그 디렉토리 설정
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# 기본 핸들러 제거
logger.remove()

# 1. 콘솔 핸들러 (간결한 출력)
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    enqueue=True
)

# 2. 에러 파일 핸들러
logger.add(
    os.path.join(LOG_DIR, "error.log"),
    rotation="10 MB",
    retention="10 days",
    level="ERROR",
    enqueue=True
)

# 3. LLM 통신 전용 파일 핸들러 (filter 사용)
def llm_filter(record):
    return record["extra"].get("type") == "LLM"

logger.add(
    os.path.join(LOG_DIR, "llm_communication.log"),
    format="[{time:YYYY-MM-DD HH:mm:ss}] {message}",
    filter=llm_filter,
    level="INFO",
    enqueue=True
)

def log_llm_event(node_name: str, message: str, details: str = None):
    """
    LLM 통신 및 노드 활동을 전용 로그 파일과 콘솔에 기록합니다.
    """
    log_entry = f"[{node_name}] {message}"
    if details:
        log_entry += f"\n--- 상세 내용 ---\n{details}\n----------------"
    
    # bind를 사용하여 llm_filter가 감지 가능하게 함
    logger.bind(type="LLM").info(log_entry)

# Export
__all__ = ["logger", "log_llm_event"]