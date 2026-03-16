import sys
import os
from loguru import logger
from datetime import datetime

# ==========================================
# 로그 경로 및 디렉토리 설정
# ==========================================
# 프로젝트 루트 디렉토리 및 logs 폴더 경로 설정
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")

# 기본 loguru 핸들러(콘솔 출력 등 기본값)를 제거하여 중복 출력을 방지하고
# 우리가 원하는 커스텀 핸들러만 사용하도록 커스터마이징합니다.
logger.remove()

# ==========================================
# 1. 전역 콘솔 핸들러 (개발자 확인용)
# ==========================================
# 표준 에러(stderr) 스트림으로 로그를 출력하며, 가독성을 위해 컬러 포맷팅을 적용합니다.
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    enqueue=True # 멀티프로세스/스레드 환경에서 안전하게 로그를 큐에 담아 비동기적으로 처리합니다.
)

# ==========================================
# 2. 전역 INFO 파일 핸들러 (날짜별 자동 분류)
# ==========================================
# 시스템 전반의 INFO 레벨 이상의 모든 로그를 파일로 기록합니다.
INFO_LOG_PATH = os.path.join(LOG_DIR, "{time:YYYY-MM-DD}", "info.log")

logger.add(
    INFO_LOG_PATH,
    rotation="20 MB",    # INFO 로그는 양이 많을 수 있으므로 20MB 단위로 회전
    retention="15 days", # 최소 15일치 보관
    level="INFO",
    enqueue=True,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

# ==========================================
# 3. 전역 에러 파일 핸들러 (날짜별 자동 분류)
# ==========================================
# 시스템 전반에서 발생하는 ERROR(또는 CRITICAL) 레벨의 로그만 따로 모아서 기록합니다.
ERROR_LOG_PATH = os.path.join(LOG_DIR, "{time:YYYY-MM-DD}", "error.log")

logger.add(
    ERROR_LOG_PATH,
    rotation="10 MB",    # 파일 크기가 10MB가 넘으면 새 파일을 생성합니다.
    retention="10 days", # 최근 10일치 로그만 보관하고 나머지는 삭제하여 용량을 관리합니다.
    level="ERROR",
    enqueue=True
)

def _escape_log_message(msg: str) -> str:
    """Loguru의 opt(colors=True)에서 < 문자를 태그로 오해하지 않도록 이스케이프 처리합니다."""
    if not msg:
        return msg
    return msg.replace("<", "\\<")

# ==========================================
# 3. LLM 통신 및 작업 로그 헬퍼
# ==========================================
def log_llm_event(node_name: str, message: str, details: str = None, token_info: dict = None):
    """
    LLM API 호출 전후의 이벤트 및 노드 활동을 통합하여 기록합니다.
    (콘솔 창에서 에이전트 간 대화를 알아보기 쉽도록 색상을 적용합니다)
    
    Args:
        node_name (str): 현재 로그를 남기는 노드나 모듈의 이름 (예: 'Gemini', 'Crawler')
        message (str): 로그 요약 메시지
        details (str, optional): 프롬프트나 응답 본문 같은 긴 상세 내용
        token_info (dict, optional): {'prompt_tokens': int, 'completion_tokens': int} 형태의 토큰 사용량 정보
    """
    # 에이전트 식별을 위한 아이콘 및 색상 맵 (Loguru 컬러 태그 활용)
    AGENT_COLORS = {
        "EvidenceAgent": "<light-blue>",
        "IssueAgent": "<light-yellow>",
        "WriterAgent": "<light-magenta>",
        "EditorAgent": "<light-cyan>",
        "JudgeAgent": "<light-red>",
        "LocalLLM": "<green>",
        "Gemini": "<blue>",
        "DraftGen": "<white>"
    }
    
    # 노드 이름에 매칭되는 색상을 찾고 없으면 기본 흰색 사용
    color_tag = "<white>"
    for key, color in AGENT_COLORS.items():
        if key.lower() in node_name.lower():
            color_tag = color
            break
            
    # 컬러가 적용된 헤더
    header_title = f"[ {node_name} ]"
    header = f"{color_tag}╔════════ {header_title:<15} ═══════════════════════════</>"
    
    # 메시지 및 상세 내용 이스케이프 처리
    escaped_message = _escape_log_message(message)
    log_entry = f"\n{header}\n{color_tag}║</> {escaped_message}"
    
    # 토큰 사용량이 전달된 경우, 요약 및 합계를 계산하여 메시지에 포함합니다.
    if token_info:
        p_tokens = token_info.get('prompt_tokens', 0)
        c_tokens = token_info.get('completion_tokens', 0)
        t_tokens = p_tokens + c_tokens
        log_entry += f" {color_tag}(Tokens: P={p_tokens}, C={c_tokens}, T={t_tokens})</>"
    
    # 상세 내용(details)이 있으면 구분선과 함께 로그 엔트리에 추가합니다.
    if details:
        details_title = "상세 내용"
        log_entry += f"\n{color_tag}╠ {details_title:<45} </>\n"
        # 여러 줄의 details를 보기 좋게 들여쓰기 처리
        escaped_details = _escape_log_message(details)
        indented_details = "\n".join([f"{color_tag}║</> {line}" for line in escaped_details.split("\n")])
        log_entry += f"{indented_details}"
        
    log_entry += f"\n{color_tag}╚════════════════════════════════════════════════════════</>\n"
    
    # opt(colors=True)를 사용하여 loguru의 기본 INFO 레벨에 컬러 태그를 허용하여 출력합니다.
    logger.opt(colors=True).info(log_entry)

# ==========================================
# 4. 세션 기반 독립 로깅 제어 (Work/Job 단위 관리)
# ==========================================
def start_job_logging(job_type: str) -> tuple[int, str]:
    """
    특정 비즈니스 작업(크롤링, 클러스터링 등)이 시작될 때 독립적인 로그 파일을 생성합니다.
    이를 통해 여러 작업이 섞이지 않고 각 실행건마다 고유한 로그 파일을 가질 수 있습니다.
    
    Args:
        job_type (str): 작업의 종류 (예: 'crawl', 'cluster')
        
    Returns:
        tuple[int, str]: 생성된 핸들러의 ID (로깅 중단 시 필요)와 로그 파일의 전체 경로
    """
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S") # 시분초를 포함하여 파일명 중복 방지
    
    date_dir = os.path.join(LOG_DIR, date_str)
    os.makedirs(date_dir, exist_ok=True)
    
    # 유니크한 파일명 생성: 예) crawl_143005.log
    log_filename = f"{job_type}_{time_str}.log"
    log_path = os.path.join(date_dir, log_filename)
    
    # 작업별 필터 설정:
    # logger.bind(job_type=...) 되어 호출된 로그만 이 파일 핸들러가 가로채서 기록합니다.
    handler_id = logger.add(
        log_path,
        format="[{time:YYYY-MM-DD HH:mm:ss}] {message}",
        filter=lambda record: record["extra"].get("job_type") == job_type,
        level="INFO",
        enqueue=True
    )
    return handler_id, log_path

def stop_job_logging(handler_id: int):
    """
    작업 완료 후 생성했던 독립 로그 파일 핸들러를 제거하여 리소스를 정리하고 파일 쓰기를 종료합니다.
    """
    logger.remove(handler_id)

def finalize_job_log(old_path: str, status: str):
    """
    작업 종료 후 로그 파일의 이름을 최종 상태(성공 또는 실패)와 함께 업데이트합니다.
    예: crawl_143005.log -> crawl_143005_success.log
    
    Args:
        old_path (str): 원래 생성되었던 로그 파일의 경로
        status (str): 최종 작업 결과 상태 ('success' 또는 'failed')
        
    Returns:
        str: 실제 변경된(혹은 원본) 파일 경로
    """
    if not os.path.exists(old_path):
        return old_path
    
    directory = os.path.dirname(old_path)
    filename = os.path.basename(old_path)
    name, ext = os.path.splitext(filename)
    
    # 파일명 뒤에 상태값 추가
    new_filename = f"{name}_{status}{ext}"
    new_path = os.path.join(directory, new_filename)
    
    try:
        # 파일 이름 변경 (rename)
        os.rename(old_path, new_path)
        return new_path
    except Exception as e:
        # 이름 변경 중 에러 발생 시(예: 파일 잠금) 기본 에러 로그에만 남기고 원래 경로 유지
        logger.error(f"로그 파일 결과 상태 명명 실패 (Rename failed): {e}")
        return old_path

# ==========================================
# 모듈 외부 노출 설정
# ==========================================
__all__ = ["logger", "log_llm_event", "start_job_logging", "stop_job_logging", "finalize_job_log"]
