"""
[크롤링 + 클러스터링 통합 테스트]
크롤링 → 저장 → 클러스터링 순서로 통합 실행합니다.

실행 예시:
  # 사설 + 정치 기사 모두 수집 및 클러스터링 (분리 실행)
  python run_crawl_cluster.py --both

  # 사설만
  python run_crawl_cluster.py --mode editorial

  # 정치만
  python run_crawl_cluster.py --mode politics

  # 특정 날짜 사설
  python run_crawl_cluster.py --mode editorial --start 20260330 --end 20260331
"""
import sys
import os
import argparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.core.database import SessionLocal
from app.scroller.service import ScrollerService
from app.domains.system.models import SystemSettings
from app.core.logger import logger


def seed_settings():
    """초기 시스템 설정(gemini_only) 주입"""
    db = SessionLocal()
    try:
        existing = db.query(SystemSettings).first()
        if not existing:
            new_setting = SystemSettings(id=1, llm_mode="gemini_only")
            db.add(new_setting)
            db.commit()
            logger.info("✅ 초기 시스템 설정(gemini_only) 주입 완료!")
        else:
            logger.info(f"ℹ️ 기존 설정 유지 중: {existing.llm_mode}")
    finally:
        db.close()


def run_crawl_and_cluster(
    article_mode: str = "editorial",
    start_date: str = None,
    end_date: str = None,
    llm_mode: str = None
) -> dict:
    """
    크롤링 + 클러스터링 통합 실행

    Args:
        article_mode: "politics" (정치) 또는 "editorial" (사설/오피니언)
        start_date: 수집 시작일 (YYYYMMDD). None이면 오늘 기준 기본 범위
        end_date: 수집 종료일 (YYYYMMDD). None이면 start_date와 동일
        llm_mode: LLM 모드 (None이면 DB 설정값 사용)

    Returns:
        {"saved_count": int, "issue_count": int}
    """
    mode_label = "사설(오피니언)" if article_mode == "editorial" else "정치"
    result = {"saved_count": 0, "issue_count": 0}

    logger.info(f"🚀 [Pipeline:{mode_label}] 뉴스 크롤링 및 이슈 클러스터링 파이프라인 시작...")
    logger.info(f"   - 기사 유형: [{mode_label}]")
    logger.info(f"   - 날짜 범위: {start_date or '기본(오늘~DAYS_TO_CRAWL)'} ~ {end_date or ''}")

    seed_settings()

    db = SessionLocal()
    try:
        # 0. 글로벌 설정 확인
        setting = db.query(SystemSettings).first()
        active_mode = llm_mode or (setting.llm_mode if setting else "gemini_only")
        logger.info(f"📡 [Settings] 현재 LLM 모드: {active_mode}")

        # --- 1단계: 크롤링 ---
        logger.info(f"=== [{mode_label}] 1단계: 크롤링 (LLM: {active_mode}) ===")

        from app.agents.scout import ScoutAgent
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        agent = ScoutAgent(db)

        # 날짜 범위 파싱
        date_range = None
        if start_date:
            from datetime import datetime, timedelta
            start_dt = datetime.strptime(start_date, "%Y%m%d")
            end_dt = datetime.strptime(end_date, "%Y%m%d") if end_date else start_dt
            date_range = []
            current = start_dt
            while current <= end_dt:
                date_range.append(current.strftime("%Y%m%d"))
                current += timedelta(days=1)
            logger.info(f"📅 수집 대상 날짜: {date_range}")

        loop = asyncio.get_event_loop()
        all_news = loop.run_until_complete(
            agent.run_async_crawl(
                article_mode=article_mode,
                custom_dates=date_range
            )
        )
        logger.success(f"✅ [{mode_label}] 크롤링 완료: {len(all_news)}건 수집")

        if all_news:
            save_result = agent.node_save_articles({"raw_articles": all_news})
            saved_count = save_result.get("saved_count", 0)
            result["saved_count"] = saved_count
            logger.success(f"💾 [{mode_label}] DB 저장 완료: {saved_count}건 신규 저장")
        else:
            logger.warning(f"⚠️ [{mode_label}] 수집된 기사가 없어 클러스터링을 건너뜁니다.")
            return result

        # --- 2단계: 클러스터링 ---
        logger.info(f"=== [{mode_label}] 2단계: 미분류 기사 이슈 클러스터링 ===")
        service = ScrollerService(db)
        cluster_result = service.execute_clustering(mode=active_mode, article_mode=article_mode)

        # saved_issue_count 필드 직접 사용 (정규식 파싱 오류 방지)
        issue_count = cluster_result.saved_issue_count if cluster_result else 0
        result["issue_count"] = issue_count

        logger.success(f"✅ [{mode_label}] 클러스터링 완료: 이슈 {issue_count}건 생성")
        logger.success(f"🎉 [{mode_label}] 파이프라인 성공 종료! (신규 기사 {saved_count}건 → 이슈 {issue_count}건)")

    except Exception as e:
        logger.critical(f"❌ [{mode_label}] 파이프라인 치명적 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="크롤링 + 클러스터링 통합 테스트")
    parser.add_argument(
        "--mode",
        choices=["politics", "editorial"],
        default=None,
        help="기사 섹션 유형: 'politics'(정치) 또는 'editorial'(사설/오피니언). --both 사용 시 무시됨"
    )
    parser.add_argument(
        "--both",
        action="store_true",
        help="사설(editorial) → 정치(politics) 순서로 두 파이프라인을 모두 순차 실행합니다."
    )
    parser.add_argument(
        "--start",
        default=None,
        help="수집 시작일 (YYYYMMDD). 예: 20260330"
    )
    parser.add_argument(
        "--end",
        default=None,
        help="수집 종료일 (YYYYMMDD). 예: 20260331"
    )
    parser.add_argument(
        "--llm",
        default=None,
        choices=["gemini_only", "local_only", "local_priority"],
        help="LLM 모드 (기본값: DB 설정값 또는 gemini_only)"
    )
    args = parser.parse_args()

    # 인자 없이 실행(F5)할 때는 --both 모드를 기본으로 동작
    if not args.mode and not args.both:
        args.both = True

    if args.both:
        # 사설 → 정치 순서로 파이프라인을 분리하여 순차 실행
        logger.info("🔄 [Both Mode] 사설 + 정치 파이프라인을 순차적으로 실행합니다.")
        logger.info("━" * 60)
        logger.info("📰 [1/2] 사설(Editorial) 파이프라인 시작")
        logger.info("━" * 60)
        editorial_result = run_crawl_and_cluster(
            article_mode="editorial",
            start_date=args.start,
            end_date=args.end,
            llm_mode=args.llm
        )
        logger.info("━" * 60)
        logger.info("🗞️  [2/2] 정치(Politics) 파이프라인 시작")
        logger.info("━" * 60)
        politics_result = run_crawl_and_cluster(
            article_mode="politics",
            start_date=args.start,
            end_date=args.end,
            llm_mode=args.llm
        )
        logger.info("━" * 60)
        logger.success("🎉 [Both Mode] 전체 파이프라인 완료! 결과 요약:")
        logger.success(f"   📰 사설(Editorial): 신규 기사 {editorial_result.get('saved_count', 0)}건 → 이슈 {editorial_result.get('issue_count', 0)}건 생성")
        logger.success(f"   🗞️  정치(Politics):  신규 기사 {politics_result.get('saved_count', 0)}건 → 이슈 {politics_result.get('issue_count', 0)}건 생성")
        logger.info("━" * 60)
    else:
        # 단일 모드 (기본값: editorial)
        mode = args.mode or "editorial"
        run_crawl_and_cluster(
            article_mode=mode,
            start_date=args.start,
            end_date=args.end,
            llm_mode=args.llm
        )
