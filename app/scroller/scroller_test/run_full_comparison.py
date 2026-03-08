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
from app.core.logger import logger, log_llm_event

def run_full_pipeline():
    """
    create_comparison_graph를 사용하여 
    [크롤링 -> 저장 -> 클러스터 -> 명명 -> 청소 -> 분석 -> 기사 작성 -> 검수]
    전 과정을 한 번에 실행합니다.
    """
    logger.info("🚀 [Full Pipeline] 통합 파이프라인(Comparison Graph) 실행 시작...")
    
    db: Session = SessionLocal()
    
    try:
        # 1. 그래프 컴파일
        logger.info("🛠️  에이전트 그래프 컴파일 중...")
        app = create_comparison_graph(db)
        
        # 2. DB에서 시스템 설정(LLM 모드) 조회
        from app.scroller.repository import ScrollerRepository
        repo = ScrollerRepository(db)
        settings = repo.get_system_settings()
        llm_mode = settings.llm_mode
        
        logger.info(f"⚙️  DB 설정 기반 LLM 모드 로드: {llm_mode}")
        
        # 3. 초기 상태 설정
        # ComparisonState 정의와 100% 일치하도록 구성
        initial_state = {
            "llm_mode": llm_mode,         # DB 설정을 따름 (gemini_only, local_priority, local_only)
            "issue_id": None,              # 클러스터링 단계에서 자동 결정됨
            "raw_articles": [],
            "unclustered_articles": [],
            "clustered_topics": [],
            "articles": [],
            "claim_cards": [],
            "structured_issues": [],
            "draft_article": "",
            "edited_article": "",
            "edit_log": "",
            "judge_status": "",
            "judge_feedback": "",
            "retry_count": 0,
            "messages": [],
            "error": ""
        }
        
        # 3. 그래프 실행
        config = {"configurable": {"thread_id": "full_pipeline_run"}}
        logger.info("🏃 그래프 워크플로우를 시작합니다. (로그는 info.log 및 콘솔에서 확인 가능)")
        
        final_state = app.invoke(initial_state, config=config)
        
        # 4. 결과 출력
        logger.success("🎉 [Full Pipeline] 파이프라인 실행 종료!")
        
        if final_state.get("error"):
            logger.error(f"❌ 중단 원인: {final_state['error']}")
        else:
            final_issue_id = final_state.get("issue_id")
            final_article = final_state.get("edited_article", "")
            
            if final_article and "오류가 발생" not in final_article:
                logger.success(f"✅ 최종 비평 기사 생성 성공! (이슈 ID: {final_issue_id})")
                print("\n" + "="*50)
                print("--- FINAL ARTICLE ---")
                print(final_article)
                print("="*50 + "\n")
            else:
                logger.warning("⚠️  분석까지 진행되었으나 최종 기사 생성에는 실패했거나 분석 대상 이슈를 찾지 못했습니다.")

    except Exception as e:
        logger.critical(f"💥 파이프라인 실행 중 치명적 오류 발생: {e}")
    finally:
        db.close()
        logger.info("👋 프로세스를 종료합니다.")

if __name__ == "__main__":
    run_full_pipeline()
