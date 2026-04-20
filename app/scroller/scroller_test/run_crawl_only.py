import sys
import os
import argparse
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.core.database import SessionLocal
from app.core.logger import logger
from app.domains.system.models import SystemSettings


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


def run_crawl_only(
    article_mode: str = "editorial",  # 랭킹 말고 사설/칼럼만 가져오는 이전 모드로 복구!
    start_date: str = "20260330",     
    end_date: str = "20260331",       
    llm_mode: str = "gemini_only"
):
    """
    크롤링 단독 실행 함수
    """
    logger.info(f"🚀 [Crawl Only] 크롤링 단독 테스트 시작")
    logger.info(f"   - 모드: 기존 랭킹 크롤러 ({'사설(오피니언)' if article_mode == 'editorial' else '정치'})")
    logger.info(f"   - 날짜 범위: {start_date or '오늘'} ~ {end_date or start_date or '기본 범위'}")

    db = SessionLocal()
    seed_settings(db)

    try:
        from app.agents.scout import ScoutAgent
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        agent = ScoutAgent(db)

        # 수집 모드 분기
        loop = asyncio.get_event_loop()
        
        # 기존 랭킹 파이프라인으로 일괄 실행
        date_range = None
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y%m%d")
            end_dt = datetime.strptime(end_date, "%Y%m%d") if end_date else start_dt
            date_range = []
            current = start_dt
            while current <= end_dt:
                date_range.append(current.strftime("%Y%m%d"))
                current += timedelta(days=1)
            logger.info(f"📅 수집 대상 날짜: {date_range}")

        all_news = loop.run_until_complete(
            agent.run_async_crawl(
                article_mode=article_mode,
                custom_dates=date_range
            )
        )

        logger.success(f"✅ [Crawl Only] 본문 수집 완료: 총 {len(all_news)}건")

        # DB 저장
        if all_news:
            logger.info(f"💾 [Crawl Only] DB 저장 시작...")
            save_result = agent.node_save_articles({"raw_articles": all_news})
            saved_count = save_result.get("saved_count", 0)
            logger.success(f"✅ [Crawl Only] DB 저장 완료: {saved_count}건 신규 저장")
        else:
            logger.warning("⚠️ [Crawl Only] 수집된 기사가 없습니다.")

        return all_news

    except Exception as e:
        logger.critical(f"❌ [Crawl Only] 크롤링 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="뉴스 크롤링 단독 테스트")
    parser.add_argument(
        "--mode",
        choices=["politics", "editorial"],
        default="editorial", 
        help="기사 섹션 유형: 'politics', 'editorial'. 기본값: editorial"
    )
    parser.add_argument(
        "--start",
        default="20260329",
        help="수집 시작일 (YYYYMMDD). 예: 20260330"
    )
    parser.add_argument(
        "--end",
        default="20260331",
        help="수집 종료일 (YYYYMMDD). 예: 20260331"
    )
    parser.add_argument(
        "--llm",
        default="gemini_only",
        choices=["gemini_only", "local_only", "local_priority"],
        help="LLM 모드 (기본값: gemini_only)"
    )
    args = parser.parse_args()

    run_crawl_only(
        article_mode=args.mode,
        start_date=args.start,
        end_date=args.end,
        llm_mode=args.llm
    )
