"""
[클러스터링 전용 테스트]
DB에 이미 저장된 미분류 기사들에 대해 클러스터링만 단독으로 실행합니다.
크롤링 없이 기존의 unclustered 기사들을 군집화하여 이슈를 생성합니다.

실행 예시:
  python run_cluster_only.py
"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.core.database import SessionLocal
from app.core.logger import logger


def seed_settings(db):
    """초기 시스템 설정(gemini_only) 주입"""
    from app.domains.system.models import SystemSettings
    existing = db.query(SystemSettings).first()
    if not existing:
        new_setting = SystemSettings(id=1, llm_mode="gemini_only")
        db.add(new_setting)
        db.commit()
        logger.info("✅ 초기 시스템 설정(gemini_only) 주입 완료!")
    else:
        logger.info(f"ℹ️ 기존 설정 유지 중: {existing.llm_mode}")


def run_cluster_only(llm_mode: str = None):
    """
    클러스터링 단독 실행

    Args:
        llm_mode: LLM 모드 (None이면 DB 설정값 사용)
    """
    logger.info("🚀 [Cluster Only] 클러스터링 단독 테스트 시작")

    db = SessionLocal()
    seed_settings(db)

    try:
        from app.scroller.service import ScrollerService
        from app.domains.system.models import SystemSettings

        # LLM 모드 결정
        if not llm_mode:
            setting = db.query(SystemSettings).first()
            llm_mode = setting.llm_mode if setting else "gemini_only"

        logger.info(f"⚙️  LLM 모드: {llm_mode}")

        service = ScrollerService(db)

        # 미분류 기사 수 확인
        from app.scroller.repository import ScrollerRepository
        repo = ScrollerRepository(db)
        unclustered = repo.get_unclustered_articles()
        logger.info(f"📋 [Cluster Only] 미분류 기사 수: {len(unclustered)}건")

        if not unclustered:
            logger.warning("⚠️ [Cluster Only] 클러스터링할 미분류 기사가 없습니다.")
            logger.info("   → 먼저 run_crawl_only.py 를 실행하여 기사를 수집하세요.")
            return

        # 클러스터링 실행
        logger.info("=== 클러스터링 시작 ===")
        cluster_result = service.execute_clustering(mode=llm_mode)

        logger.success(f"✅ [Cluster Only] 클러스터링 완료!")
        logger.success(f"   - 생성된 이슈 수: {cluster_result.saved_issue_count}건")
        logger.success(f"   - 상태: {cluster_result.status}")
        logger.info(f"   - 메시지: {cluster_result.message}")

        return cluster_result

    except Exception as e:
        logger.critical(f"❌ [Cluster Only] 클러스터링 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="클러스터링 단독 테스트")
    parser.add_argument(
        "--llm",
        default=None,
        choices=["gemini_only", "local_only", "local_priority"],
        help="LLM 모드 (기본값: DB 설정값 또는 gemini_only)"
    )
    args = parser.parse_args()

    run_cluster_only(llm_mode=args.llm)
