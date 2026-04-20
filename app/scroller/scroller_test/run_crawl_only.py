"""
[크롤링 전용 테스트]
뉴스 크롤링만 단독으로 실행합니다.
- 날짜 범위 지정 가능
- 사설(오피니언) 섹션 vs 정치 섹션 선택 가능
- [NEW] 특정 논문/테스트 기사들의 URL만 직접 수동으로 수집하는 기능(custom_urls 모드)

실행 예시:
  # 기본 (이제 F5 누르면 아래에 설정된 TARGET_URLS를 수동으로 긁어옵니다.)
  python run_crawl_only.py
  
  # 기존 랭킹 크롤러로 정치/사설 긁어오려면:
  python run_crawl_only.py --mode politics
"""
import sys
import os
import argparse
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# =========================================================================
# 👇 테스트하실 과거 기사 URL들을 여기에 직접 넣으세요 (F5 누르면 이 기사들이 긁힙니다)
# =========================================================================
TARGET_URLS = [
    {
        "url": "https://www.chosun.com/opinion/editorial/2026/03/31/UULCP5MYSFABNJXF5M6BYWUY3Y/",
        "press": "조선일보",
        "title": "사설 <잇단 ‘불법 대북송금’ 녹취록 공방, 전문 공개해야>",
        "pub_date": "2026-03-31"
    },
    {
        "url": "https://v.daum.net/v/PROU66Zv7P",
        "press": "한국일보",
        "title": "사설 <대북송금 진술 회유 의혹, 녹취록 전체 공개로 진실 가려라>",
        "pub_date": "2026-03-31"
    },
    {
        "url": "https://www.khan.co.kr/article/202603301810001",
        "press": "경향신문",
        "title": "사설 <쌍방울 검사의 “이재명 주범 돼야” 발언, 국조서 진상가려야>",
        "pub_date": "2026-03-30"
    },
    {
        "url": "https://n.news.naver.com/mnews/article/028/0000000000",   # 한겨레는 아직 미확인 상태로 유지
        "press": "한겨레",
        "title": "사설 <“이재명 주범 자백” 검사 녹취, ‘진술 회유’ 여부 밝혀야>",
        "pub_date": "2026-03-30"
    }
]
# =========================================================================

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

async def fetch_custom_urls(urls):
    """
    네이버 뉴스 외에 타 언론사 웹사이트도 어느 정도 긁어올 수 있는 범용 크롤러
    """
    results = []
    async with aiohttp.ClientSession() as session:
        for item in urls:
            try:
                # 000000 가짜 링크 방어
                if "0000000000" in item["url"]:
                    logger.warning(f"⏩ 실제 주소로 변경되지 않은 임시 URL 건너뜀: {item['press']}")
                    continue
                    
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                logger.info(f"   - [접속 시도] {item['press']}: {item['url']}")
                async with session.get(item["url"], headers=headers, timeout=10) as resp:
                    html = await resp.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    content = ""
                    # 1. 네이버 뉴스 양식일 경우
                    if "naver.com" in item["url"]:
                        content_area = soup.select_one('#dic_area') or soup.select_one('#newsct_article')
                        if content_area:
                            for tag in content_area.select('.img_desc, .end_photo_org'):
                                tag.extract()
                            content = content_area.get_text(strip=True)
                            
                    # 2. 범용 양식 (미디어스 같은 타 사이트)
                    else:
                        paragraphs = soup.find_all('p')
                        content = "\n".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20)
                    
                    # 날짜 파싱
                    pub_date = None
                    if item.get("pub_date"):
                        pub_date = datetime.strptime(item["pub_date"] + " 12:00:00", "%Y-%m-%d %H:%M:%S")
                    else:
                        pub_date = datetime.utcnow() + timedelta(hours=9)
                        
                    results.append({
                        "press": item["press"],
                        "title": item.get("title", "수동 수집 기사"),
                        "content": content,
                        "image_urls": [],
                        "pub_date": pub_date,
                        "reporter": "수동입력",
                        "link": item["url"]
                    })
                    logger.success(f"   - [수집 성공] {item['press']} 본문 {len(content)}자 추출 완료!")
            except Exception as e:
                logger.error(f"❌ [스크래핑 실패] {item['url']}: {e}")
    return results


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
    
    if article_mode == "custom_urls":
        logger.info(f"   - 모드: 수동 지정 URL 직접 수집 모드")
    else:
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
        
        if article_mode == "custom_urls":
            # 수동 URL 스크래퍼 실행 (TARGET_URLS 이용)
            all_news = loop.run_until_complete(fetch_custom_urls(TARGET_URLS))
        else:
            # 기존 랭킹 파이프라인
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
        choices=["politics", "editorial", "custom_urls"],
        default="editorial", 
        help="기사 섹션 유형: 'politics', 'editorial', 'custom_urls'. 기본값: editorial"
    )
    parser.add_argument(
        "--start",
        default="20260330",
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
