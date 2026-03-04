from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.scroller.schemas import SearchRequest, SearchResponse
from app.scroller.schemas import (
    CrawlRequest, ClusterRequest, CrawlResponse, ClusterResponse, 
    ResetResponse, LLMModeUpdateRequest, SettingsResponse
)
from app.scroller.service import ScrollerService
from app.scroller.service import NLPSearchService

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

@router.delete("/reset", response_model=ResetResponse, summary="기사 및 이슈 DB 완전 초기화")
def reset_database(db: Session = Depends(get_db)):
    # db 완전 초기화(테스트를 위해 필요해~~)
    service = ScrollerService(db)
    try:
        return service.execute_truncate()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/logs", summary="최근 실행 이력 조회")
def get_execution_logs(
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """
    크롤링 및 클러스터링 작업의 최근 실행 이력을 조회합니다.
    """
    service = ScrollerService(db)
    return service.get_execution_logs(limit)

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

    