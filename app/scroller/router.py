from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.scroller.schemas import SearchRequest, SearchResponse
from app.scroller.schemas import (
    CrawlRequest, ClusterRequest, CrawlResponse, ClusterResponse, 
    ResetResponse, LLMModeUpdateRequest, SettingsResponse,
    LogListResponse, LogDetailResponse, LogFileItem
)
from app.scroller.service import ScrollerService
from app.scroller.service import NLPSearchService
import os
from datetime import datetime
from app.core.logger import LOG_DIR

router = APIRouter()

@router.post("/nlp", response_model=SearchResponse)
async def search_news_nlp(request: SearchRequest, db: Session = Depends(get_db)):
    # 내부 db 검색(nlp 자연어 검색)
    service = NLPSearchService(db)
    result = service.execute_search_briefing(request.query)
    return result

@router.post("/crawl", response_model=CrawlResponse, summary="최신 정치 뉴스 크롤링")
def crawl_news(request: CrawlRequest, db: Session = Depends(get_db)):
    # 4일치 뉴스를 크롤링!! 
    service = ScrollerService(db)
    try:
        return service.execute_news_crawling(mode=request.mode)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cluster", response_model=ClusterResponse, summary="미분류 기사 AI 군집화")
def cluster_articles(request: ClusterRequest, db: Session = Depends(get_db)):
    # 클러스터링 
    service = ScrollerService(db)
    try:
        return service.execute_clustering(mode=request.mode)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/settings/llm-mode", response_model=SettingsResponse, summary="글로벌 LLM 모드 설정")
def update_llm_mode(request: LLMModeUpdateRequest, db: Session = Depends(get_db)):
    """
    시스템 전체에서 사용할 기본 LLM 모드를 설정합니다.
    """
    service = ScrollerService(db)
    try:
        new_mode = service.update_llm_mode(request.mode)
        return SettingsResponse(
            status="success",
            message=f"LLM 모드가 '{new_mode}'로 성공적으로 변경되었습니다.",
            current_mode=new_mode
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/logs", response_model=LogListResponse, summary="로그 파일 목록 조회")
def get_log_files():
    """
    서버의 logs/ 디렉토리를 스캔하여 날짜별 로그 파일 목록을 반환합니다.
    """
    if not os.path.exists(LOG_DIR):
        return {"status": "success", "logs": []}
    
    log_items = []
    # 날짜별 폴더 스캔
    for date_dir in sorted(os.listdir(LOG_DIR), reverse=True):
        full_date_path = os.path.join(LOG_DIR, date_dir)
        if not os.path.isdir(full_date_path):
            continue
            
        # 해당 날짜 폴더 내의 로그 파일 스캔
        for filename in sorted(os.listdir(full_date_path), reverse=True):
            if not filename.endswith(".log"):
                continue
                
            file_path = os.path.join(full_date_path, filename)
            stat = os.stat(file_path)
            
            log_items.append(LogFileItem(
                date=date_dir,
                filename=filename,
                size=stat.st_size,
                last_modified=datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            ))
            
    return {"status": "success", "logs": log_items}

@router.get("/logs/{date}/{filename}", response_model=LogDetailResponse, summary="로그 파일 상세 내용 조회")
def get_log_content(date: str, filename: str):
    """
    특정 날짜의 특정 로그 파일 내용을 읽어서 반환합니다.
    """
    file_path = os.path.join(LOG_DIR, date, filename)
    
    # 보안 체크: 경로 탈출 방지
    if not os.path.abspath(file_path).startswith(os.path.abspath(LOG_DIR)):
        raise HTTPException(status_code=403, detail="접근 거부된 경로입니다.")
        
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="로그 파일을 찾을 수 없습니다.")
        
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {
            "status": "success",
            "filename": filename,
            "content": content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"파일 읽기 오류: {str(e)}")

    
@router.delete("/reset", response_model=ResetResponse, summary="**주의**기사 및 이슈 DB 완전 초기화")
def reset_database(db: Session = Depends(get_db)):
    # db 완전 초기화(테스트를 위해 필요해~~)
    service = ScrollerService(db)
    try:
        return service.execute_truncate()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
