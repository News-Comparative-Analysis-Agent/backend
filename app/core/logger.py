import sys
from loguru import logger

# Remove default handler
logger.remove()

# Add a concise console handler
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    enqueue=True
)

# Optional: Add file handler for errors
logger.add(
    "logs/error.log",
    rotation="10 MB",
    retention="10 days",
    level="ERROR",
    enqueue=True
)

# Export for use in other modules
__all__ = ["logger"]


#사용예시
# from app.core.logger import logger
# logger.info("서버가 시작되었습니다!")
# logger.error("DB 연결 실패 ㅠㅠ")