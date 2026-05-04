import sys
import os
import argparse

# 프로젝트 루트 디렉토리를 sys.path에 추가
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(BASE_DIR)

from sqlalchemy.orm import Session
from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.core.database import SessionLocal
from app.scroller.graph import create_comparison_graph
from app.core.logger import logger

def run_full_pipeline(article_mode: str = "editorial"):
    """
    create_comparison_graph를 사용하여 
    [크롤링 -> 저장 -> 클러스터 -> 명명 -> 청소 -> 분석 -> 기사 작성 -> 교정 -> 검수]
    전 과정을 한 번에 실행합니다.

    Args:
        article_mode: "editorial" (사설) 또는 "politics" (정치)
    """
    mode_label = "사설(Editorial)" if article_mode == "editorial" else "정치(Politics)"
    logger.info(f"🚀 [Full Pipeline] 통합 파이프라인(Comparison Graph) 실행 시작... [{mode_label}]")
    
    db: Session = SessionLocal()
    
    try:
        # 1. 그래프 컴파일
        logger.info("🛠️  에이전트 그래프 컴파일 중...")
        app = create_comparison_graph(db)
        
        # 2. DB에서 시스템 설정(LLM 모드) 조회
        from app.scroller.repository import ScrollerRepository
        repo = ScrollerRepository(db)
        settings = repo.get_system_settings()
        llm_mode = settings.llm_mode if settings else "gemini_only"
        
        logger.info(f"⚙️  DB 설정 기반 LLM 모드 로드: {llm_mode}")
        
        # 3. 초기 상태 설정 (OverallState 정의와 일치하도록 구성)
        initial_state = {
            "llm_mode": llm_mode,
            "article_mode": article_mode,       # editorial 또는 politics 구분
            "issue_id": None,              # 특정 이슈 분석 시에만 사용 (평소엔 None)
            "all_issue_ids": [],            # 클러스터링 단계에서 채워짐
            "raw_articles": [],
            "unclustered_articles": [],
            "clustered_topic": [],
            "total_tokens": {"prompt_tokens": 0, "completion_tokens": 0},
            "messages": [],
            "error": ""
        }
        
        # 4. 그래프 실행
        config = {"configurable": {"thread_id": f"full_pipeline_{article_mode}"}}
        logger.info("🏃 그래프 워크플로우를 시작합니다. (로그는 info.log 및 콘솔에서 확인 가능)")
        
        final_state = app.invoke(initial_state, config=config)
        
        # 5. 결과 출력
        logger.success(f"🎉 [Full Pipeline] {mode_label} 파이프라인 실행 종료!")
        
        if final_state.get("error"):
            logger.error(f"❌ 중단 원인: {final_state['error']}")
        else:
            # Map-Reduce 단계에서 처리된 총 결과 확인
            issue_ids = final_state.get("all_issue_ids", [])
            if issue_ids:
                logger.success(f"✅ 총 {len(issue_ids)}개 이슈의 분석 및 기사 생성이 완료되었습니다! (Issue IDs: {issue_ids})")
            else:
                # 특정 issue_id로 단일 실행한 경우
                single_id = final_state.get("issue_id")
                if single_id:
                    logger.success(f"✅ 이슈 ID {single_id}에 대한 분석 및 기사 생성이 완료되었습니다.")
                else:
                    logger.warning("⚠️ 파이프라인이 정상 종료되었으나, 분석 대상 이슈가 없었습니다.")
            
            # 최종 토큰 사용량 출력
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
    parser = argparse.ArgumentParser(description="통합 파이프라인 실행 (크롤링 → 저장 → 클러스터링 → 분석)")
    parser.add_argument(
        "--mode",
        choices=["politics", "editorial"],
        default=None,
        help="기사 유형: 'editorial'(사설) 또는 'politics'(정치). --both 사용 시 무시됨"
    )
    parser.add_argument(
        "--both",
        action="store_true",
        help="사설(editorial) → 정치(politics) 순서로 두 파이프라인을 모두 순차 실행합니다."
    )
    args = parser.parse_args()

    # 인자 없이 실행(F5)할 때는 --both 모드를 기본으로 동작
    if not args.mode and not args.both:
        args.both = True

    if args.both:
        # 사설 → 정치 순서로 파이프라인 순차 실행
        logger.info("🔄 [Both Mode] 사설 + 정치 파이프라인을 순차적으로 실행합니다.")
        logger.info("━" * 60)
        logger.info("📰 [1/2] 사설(Editorial) 파이프라인 시작")
        logger.info("━" * 60)
        run_full_pipeline(article_mode="editorial")

        logger.info("━" * 60)
        logger.info("🗞️  [2/2] 정치(Politics) 파이프라인 시작")
        logger.info("━" * 60)
        run_full_pipeline(article_mode="politics")

        logger.info("━" * 60)
        logger.success("🎉 [Both Mode] 사설 + 정치 전체 파이프라인 완료!")
        logger.info("━" * 60)
    else:
        # 단일 모드 (기본값: editorial)
        mode = args.mode or "editorial"
        run_full_pipeline(article_mode=mode)
