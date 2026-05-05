import sys
import os

# 프로젝트 루트 디렉토리를 sys.path에 추가
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(BASE_DIR)

from sqlalchemy.orm import Session
from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.core.database import SessionLocal
from app.scroller.graph import create_comparison_graph
from app.core.logger import logger

def run_politics_pipeline():
    """
    정치(Politics) 전용 파이프라인
    [크롤링 -> 클러스터 -> 분석(Issue/Evidence 추출) -> 바로 종료]
    """
    article_mode = "politics"
    logger.info(f"🚀 [Politics Pipeline] 정치 기사 파이프라인 실행 시작...")
    
    db: Session = SessionLocal()
    
    try:
        logger.info("🛠️  에이전트 그래프 컴파일 중...")
        app = create_comparison_graph(db)
        
        from app.scroller.repository import ScrollerRepository
        repo = ScrollerRepository(db)
        settings = repo.get_system_settings()
        llm_mode = settings.llm_mode if settings else "local_only"
        
        logger.info(f"⚙️  DB 설정 기반 LLM 모드 로드: {llm_mode}")
        
        initial_state = {
            "llm_mode": llm_mode,
            "article_mode": article_mode,
            "issue_id": None,
            "all_issue_ids": [],
            "raw_articles": [],
            "unclustered_articles": [],
            "clustered_topic": [],
            "total_tokens": {"prompt_tokens": 0, "completion_tokens": 0},
            "messages": [],
            "error": ""
        }
        
        config = {"configurable": {"thread_id": f"politics_pipeline"}}
        logger.info("🏃 정치 그래프 워크플로우를 시작합니다. (비평 기사 생성 생략)")
        
        final_state = app.invoke(initial_state, config=config)
        
        logger.success(f"🎉 [Politics Pipeline] 정치 파이프라인 실행 종료!")
        
        if final_state.get("error"):
            logger.error(f"❌ 중단 원인: {final_state['error']}")
        else:
            issue_ids = final_state.get("all_issue_ids", [])
            if issue_ids:
                logger.success(f"✅ 총 {len(issue_ids)}개 정치 이슈의 심층 분석이 완료되었습니다! (Issue IDs: {issue_ids})")
            
            tokens = final_state.get("total_tokens", {})
            logger.info(f"📊 Total Tokens used in this run: {tokens}")

    except Exception as e:
        logger.critical(f"💥 파이프라인 실행 중 치명적 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()
        logger.info("👋 프로세스를 종료합니다.")

if __name__ == "__main__":
    run_politics_pipeline()
