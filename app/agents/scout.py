import asyncio
import aiohttp
import hashlib
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from app.agents.state import CrawlState
from app.scroller.repository import ScrollerRepository
from app.core.logger import logger, log_llm_event
from app.domains.articles.models import Article

TARGET_PRESS_DICT = {
    # 🔵 진보/개혁 (Progressive) - 7개
    "한겨레": "028", "경향신문": "032", "오마이뉴스": "047", "MBC": "214",
    "JTBC": "437", "노컷뉴스": "079", "프레시안": "002",
    
    # 🔴 보수/경제 (Conservative) - 7개
    "조선일보": "023", "동아일보": "020", "중앙일보": "025", "문화일보": "021",
    "한국경제": "015", "세계일보": "022", "TV조선": "448",
    
    # ⚪ 중도/팩트/통신 (Centrist & Fact) - 6개
    "연합뉴스": "001", "한국일보": "046", "YTN": "052",
    "뉴스1": "421", "뉴시스": "003", "SBS": "055"
}
DAYS_TO_CRAWL = 1

class ScoutAgent:
    """
    뉴스 크롤링 전담 에이전트
    비동기(aiohttp + asyncio)를 활용하여 네트워크 I/O 병목을 해결하고
    In-memory Set 캐싱(URL Hashing)을 통해 DB 중복 조회를 최소화합니다.
    """
    def __init__(self, db: Session):
        self.db = db
        self.repo = ScrollerRepository(db)
        # 봇 차단 방지를 위한 여러 개의 User-Agent 풀을 사용하면 더 좋습니다.
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
        # 🔥 네이버 차단 방지: 한 번에 최대 5개의 동시 요청만 허용
        self.semaphore = asyncio.Semaphore(5)

    def _get_kst_now(self) -> datetime:
        now = datetime.utcnow() + timedelta(hours=9)
        return now

    def _get_existing_url_hashes(self) -> set:
        """최근 데이터의 URL을 로드하여 해시 Set으로 반환 (In-memory Caching)"""
        cutoff_date = self._get_kst_now() - timedelta(days=DAYS_TO_CRAWL + 1)
        # DB에서 최근 기사 URL만 가져오기
        recent_articles = self.db.query(Article.url).filter(Article.published_at >= cutoff_date).all()
        
        url_hashes = set()
        for art in recent_articles:
            url_hash = hashlib.sha256(art.url.encode('utf-8')).hexdigest()
            url_hashes.add(url_hash)
        return url_hashes

    async def _fetch_html(self, session: aiohttp.ClientSession, url: str, max_retries=3) -> str:
        """단일 URL에 비동기 GET 요청 수행 (세마포어 적용)"""
        async with self.semaphore: # 🔥 동시에 5개만 실행됨
            for attempt in range(max_retries):
                try:
                    # 봇처럼 보이지 않기 위해 요청 전에 아주 짧은 난수 딜레이를 줌 (선택 사항)
                    # await asyncio.sleep(random.uniform(0.1, 0.5))
                    async with session.get(url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status == 200:
                            return await response.text()
                        elif response.status == 429:
                            logger.warning(f"🚨 [ScoutAgent] 429 Too Many Requests (Rate limit): {url}")
                            await asyncio.sleep(3) # 잠시 멈췄다 재시도
                except asyncio.TimeoutError:
                    logger.warning(f"⌛ [ScoutAgent] 타임아웃 발생 (시도 {attempt+1}/{max_retries}): {url}")
                except Exception as e:
                    logger.error(f"❌ [ScoutAgent] HTTP 요청 에러 ({url}): {e}")
                    
                await asyncio.sleep(1) # 실패 시 1초 대기 후 재시도
            return None

    async def _parse_article_detail(self, session: aiohttp.ClientSession, link: str, title: str, press_name: str) -> dict:
        """기사 상세 페이지를 비동기로 파싱"""
        html = await self._fetch_html(session, link)
        if not html:
            return None
            
        soup = BeautifulSoup(html, 'html.parser')
        
        # 섹션 파싱
        section = ""
        meta_section = soup.select_one('meta[property="article:section"]')
        if meta_section:
            section = meta_section['content']
        else:
            cat_tag = soup.select_one('.media_end_categorize_item')
            if cat_tag:
                section = cat_tag.get_text(strip=True)
        
        # 정치 섹션 필터링
        if section != "정치":
            return None
            
        # 🔥 본문 파싱 셀렉터 강화 (포토뉴스 등 방어)
        content_area = soup.select_one('#dic_area') or soup.select_one('#newsct_article') or soup.select_one('.go_trans._article_content')
        content = ""
        if content_area:
            for tag in content_area.select('.img_desc, .end_photo_org, .media_end_summary, .byline_s'):
                tag.extract()
            content = content_area.get_text(strip=True)
            
        if len(content) < 50: # 너무 짧은 기사(사진만 있는 경우 등) 방어
            return None
            
        # 이미지 및 날짜
        img_tag = soup.select_one('meta[property="og:image"]')
        image_url = img_tag['content'] if img_tag else ""
        date_tag = soup.select_one('.media_end_head_info_datestamp span')
        pub_date = date_tag['data-date-time'] if date_tag else ""
        
        # 기자 이름
        reporter = ""
        reporter_tag = soup.select_one('.media_end_head_journalist_name') or soup.select_one('.byline_s')
        if reporter_tag:
            reporter = reporter_tag.get_text(strip=True).replace('기자', '').strip()

        return {
            "press": press_name,
            "title": title,
            "content": content,
            "image_url": image_url,
            "pub_date": pub_date,
            "reporter": reporter,
            "link": link
        }

    async def _crawl_ranking_page(self, session: aiohttp.ClientSession, press_name: str, oid: str, date_str: str, existing_hashes: set) -> list:
        """특정 언론사의 특정 날짜 랭킹 페이지 수집 및 본문 긁어오기"""
        url = f"https://news.naver.com/main/ranking/office.naver?officeId={oid}&date={date_str}"
        html = await self._fetch_html(session, url, max_retries=2)
        if not html:
            return []
            
        soup = BeautifulSoup(html, 'html.parser')
        list_items = soup.select('.rankingnews_list li')
        
        tasks = []
        collected_count = 0
        
        for item in list_items:
            if collected_count >= 20: # 각 언론사당 20개 제한
                break
                
            link_tag = item.select_one('a')
            if not link_tag: continue
            
            link = link_tag['href']
            if link.startswith("/"): link = "https://news.naver.com" + link
            
            # URL Hashing & Caching Check
            link_hash = hashlib.sha256(link.encode('utf-8')).hexdigest()
            if link_hash in existing_hashes:
                continue
                
            # 임시로 Set에 추가하여 중복 스크래핑 방지
            existing_hashes.add(link_hash)
            
            title = link_tag.get_text(strip=True)
            tasks.append(self._parse_article_detail(session, link, title, press_name))
            collected_count += 1
            
        # 상세 파싱 병렬(비동기) 실행
        if not tasks:
            return []
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # 에러 처리 및 None 필터링
        valid_results = [res for res in results if res and not isinstance(res, Exception)]
        return valid_results

    async def _crawl_headline_news(self, session: aiohttp.ClientSession, existing_hashes: set) -> list:
        """정치 섹션 메인 헤드라인 뉴스 수집 (많이 본 뉴스 랭킹에 오르기 전 실시간/주요 기사 포착)"""
        url = "https://news.naver.com/section/100"
        html = await self._fetch_html(session, url, max_retries=2)
        if not html:
            return []
            
        soup = BeautifulSoup(html, 'html.parser')
        # 네이버 뉴스 정치 메인 헤드라인 영역
        items = soup.select('.as_headline .sa_text, .sa_list .sa_text')
        
        tasks = []
        for item in items:
            press_tag = item.select_one('.sa_text_press')
            title_tag = item.select_one('.sa_text_title')
            link_tag = item.select_one('a')
            
            if not (press_tag and title_tag and link_tag):
                continue
                
            press_name = press_tag.get_text(strip=True).replace('언론사 선정', '').strip()
            # 타겟 언론사 소속 기사만 수집
            if press_name not in TARGET_PRESS_DICT:
                continue
                
            link = link_tag['href']
            if link.startswith("/"): link = "https://news.naver.com" + link
            
            # URL Hashing Check
            link_hash = hashlib.sha256(link.encode('utf-8')).hexdigest()
            if link_hash in existing_hashes:
                continue
                
            existing_hashes.add(link_hash)
            title = title_tag.get_text(strip=True)
            
            tasks.append(self._parse_article_detail(session, link, title, press_name))
            
        if not tasks:
            return []
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [res for res in results if res and not isinstance(res, Exception)]

    async def run_async_crawl(self) -> list:
        """비동기 크롤러 실행 엔트리"""
        logger.info("⚡ In-memory URL Hash 캐싱 로드 중...")
        existing_hashes = self._get_existing_url_hashes()
        logger.info(f"⚡ {len(existing_hashes)}개의 URL Hash 로드 완료.")
        
        today = self._get_kst_now()
        tasks = []
        
        # aiohttp ClientSession 생성 및 동시 요청
        async with aiohttp.ClientSession() as session:
            # 1. 정치 섹션 메인 헤드라인 뉴스 수집 태스크 추가 (실시간 주요 뉴스 포착)
            tasks.append(self._crawl_headline_news(session, existing_hashes))
            
            for day_offset in range(DAYS_TO_CRAWL):
                target_date = today - timedelta(days=day_offset)
                date_str = target_date.strftime("%Y%m%d")
                
                for press_name, oid in TARGET_PRESS_DICT.items():
                    tasks.append(self._crawl_ranking_page(session, press_name, oid, date_str, existing_hashes))
            
            logger.info(f"⚡ {len(tasks)}개의 수집 태스크(헤드라인+랭킹) 병렬 실행 시작...")
            results = await asyncio.gather(*tasks)
            
        # 2차원 리스트 플래튼
        all_news = []
        for res_list in results:
            all_news.extend(res_list)
            
        if all_news:
            logger.info("📄 [ScoutAgent:Crawl] 수집된 기사 리스트:")
            for i, art in enumerate(all_news, 1):
                logger.info(f"   {i}. [{art['press']}] {art['title']}")
                
        return all_news

    def cleanup_old_data(self, state: CrawlState = None) -> dict:
        """오래된 기사 캐시 및 DB 데이터 정리"""
        log_llm_event("ScoutAgent", "데이터 클린업 시작")
        deleted_count = self.repo.delete_old_articles(days=30)
        msg = f"과거 데이터 삭제 완료: {deleted_count}건"
        return {"messages": [msg]}

    def node_crawl(self, state: CrawlState) -> dict:
        """
        [Node] LangGraph에서 호출하는 엔트리 포인트 (동기 래퍼)
        """
        log_llm_event("ScoutAgent", "비동기 크롤러 노드 시작")
        
        # 과거 데이터 삭제
        cleanup_res = self.cleanup_old_data(state)
        cleanup_msg = cleanup_res.get("messages", [""])[0] if isinstance(cleanup_res, dict) else cleanup_res
        logger.info(f"⚡ [ScoutAgent:Crawl] {cleanup_msg}")
        
        # 비동기 실행을 위한 이벤트 루프
        import nest_asyncio
        nest_asyncio.apply()
        
        loop = asyncio.get_event_loop()
        all_news = loop.run_until_complete(self.run_async_crawl())
        
        msg = f"비동기 크롤링 완료: 총 {len(all_news)}건의 유효한 정치 기사 수집됨"
        logger.success(f"⚡ [ScoutAgent:Crawl] {msg}")
        
        return {
            "raw_articles": all_news,
            "messages": [cleanup_msg, msg]
        }
    def node_save_articles(self, state: dict) -> dict:
        """
        [Node] 수집된 raw_articles를 DB에 저장합니다.
        """
        raw_articles = state.get("raw_articles", [])
        if not raw_articles:
            logger.warning("⚡ [ScoutAgent:Save] 저장할 기사 데이터가 없습니다.")
            return {"messages": ["저장할 기사 없음"]}
            
        saved_count = 0
        logger.info(f"⚡ [ScoutAgent:Save] {len(raw_articles)}건의 기사 저장 시도...")
        
        for art in raw_articles:
            try:
                # 1. 중복 체크 (URL 기준)
                if self.repo.is_article_exists(art['link']):
                    continue
                
                # 2. 언론사 ID 획득
                publisher = self.repo.get_or_create_publisher(art['press'])
                
                # 3. 기사 및 본문 저장
                image_list = [art.get('image_url')] if art.get('image_url') else []
                new_art = self.repo.save_article_with_body(
                    publisher_id=publisher.id,
                    title=art['title'],
                    url=art['link'],
                    image_urls=image_list,
                    published_at=art.get('pub_date') if art.get('pub_date') else (datetime.utcnow() + timedelta(hours=9)),
                    content=art['content'],
                    reporter=art.get('reporter')
                )
                
                if new_art:
                    saved_count += 1
                    logger.info(f"   ✅ 저장 성공: [{art['press']}] {art['title'][:40]}...")
            except Exception as e:
                logger.error(f"⚡ [ScoutAgent:Save] 기사 저장 중 오류 ([{art.get('press')}] {art.get('title')[:20]}): {e}")
                
        msg = f"총 {saved_count}건의 새로운 기사 DB 저장 완료"
        logger.success(f"⚡ [ScoutAgent:Save] {msg}")
        self.db.commit() # 최종 커밋
        
        return {"saved_count": saved_count, "messages": [msg]}
