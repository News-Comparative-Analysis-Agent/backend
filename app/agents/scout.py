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
    # 🔵 진보/개혁 (Progressive) - 4개
    "한겨레": "028", "경향신문": "032", "MBC": "214", "JTBC": "437",
    
    # 🔴 보수/경제 (Conservative) - 4개
    "조선일보": "023", "동아일보": "020", "중앙일보": "025", "문화일보": "021",
    
    # ⚪ 중도/온건 (Centrist) - 4개
    "한국일보": "046", "국민일보": "005", "서울신문": "081", "세계일보": "022"
}
DAYS_TO_CRAWL = 2

# 사설/오피니언 섹션을 나타내는 섹션명 집합 (언론사마다 표기가 다를 수 있음)
EDITORIAL_SECTIONS = {"오피니언", "사설", "칼럼", "opinion", "editorial", "社說"}

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
        # 🔥 네이버 차단 방지: 서버 딜레이(타임아웃)를 막기 위해 안정적으로 15개 동시 요청
        self.semaphore = asyncio.Semaphore(15)

    def _get_kst_now(self) -> datetime:
        """현재 KST(한국 표준시) 기준 일시 반환"""
        return datetime.utcnow() + timedelta(hours=9)

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
        async with self.semaphore: 
            for attempt in range(max_retries):
                try:
                    # 봇처럼 보이지 않기 위해 요청 전에 아주 짧은 난수 딜레이를 줌 (선택 사항)
                    # await asyncio.sleep(random.uniform(0.1, 0.5))
                    async with session.get(url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
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

    async def _parse_article_detail(
        self,
        session: aiohttp.ClientSession,
        link: str,
        title: str,
        press_name: str,
        article_mode: str = "politics"
    ) -> dict:
        """
        기사 상세 페이지를 비동기로 파싱

        Args:
            article_mode: "politics" (정치 섹션만) 또는 "editorial" (사설/오피니언 섹션만)
        """
        html = await self._fetch_html(session, link)
        if not html:
            return None
            
        soup = BeautifulSoup(html, 'lxml')
        
        # 섹션 파싱 (meta 태그 우선, 없으면 카테고리 태그)
        section = ""
        meta_section = soup.select_one('meta[property="article:section"]')
        if meta_section:
            section = meta_section['content']
        else:
            cat_tag = soup.select_one('.media_end_categorize_item')
            if cat_tag:
                section = cat_tag.get_text(strip=True)
        
        # 2. 섹션 매칭을 부분 문자열로 보완
        is_editorial_section = any(s in section for s in EDITORIAL_SECTIONS) if section else False
        
        # 제목 기반 보조 필터 추가
        EDITORIAL_TITLE_KEYWORDS = ["[사설]", "[칼럼]", "[시평]", "[논설]", "[오피니언]", "[사론]"]
        is_editorial_title = any(kw in title for kw in EDITORIAL_TITLE_KEYWORDS)
        
        if article_mode == "editorial" and not (is_editorial_section or is_editorial_title):
            return None
        elif article_mode != "editorial":
            # 기본: 정치 섹션만 수집
            if section != "정치":
                return None
            
        #  본문 파싱 셀렉터 강화 (포토뉴스 등 방어)
        content_area = soup.select_one('#dic_area') or soup.select_one('#newsct_article') or soup.select_one('.go_trans._article_content')
        content = ""
        image_urls = []
        
        # 메인 썸네일 추가
        img_tag = soup.select_one('meta[property="og:image"]')
        if img_tag and img_tag.get('content'):
            image_urls.append(img_tag['content'])

        if content_area:
            # 본문에 있는 이미지들도 추출(이미지 저장소를 위해)
            for img in content_area.select('img'):
                src = img.get('data-src') or img.get('src')
                if src and src not in image_urls and not src.startswith('data:'):
                    image_urls.append(src)
            
            for tag in content_area.select('.img_desc, .end_photo_org, .media_end_summary, .byline_s'):
                tag.extract()
            content = content_area.get_text(strip=True)
            
        if len(content) < 50: # 너무 짧은 기사(사진만 있는 경우 등) 방어
            return None
            
        # 3. 속보 필터 모드 분기
        NOISE_PREFIXES = ("[속보]", "[긴급]", "[단독]", "【속보】", "《속보》", "[포착]")
        if article_mode != "editorial":
            if any(title.strip().startswith(prefix) for prefix in NOISE_PREFIXES) and len(content) < 300:
                logger.info(f"⚡ [ScoutAgent] 속보/단신 필터링 제외: {title[:40]}")
                return None
            
        # 날짜
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
            "image_urls": image_urls,
            "pub_date": pub_date,
            "reporter": reporter,
            "link": link
        }

    async def _crawl_ranking_page(
        self,
        session: aiohttp.ClientSession,
        press_name: str,
        oid: str,
        date_str: str,
        existing_hashes: set,
        article_mode: str = "politics"
    ) -> list:
        """특정 언론사의 특정 날짜 랭킹 페이지 수집 및 본문 긁어오기"""
        url = f"https://news.naver.com/main/ranking/office.naver?officeId={oid}&date={date_str}"
        html = await self._fetch_html(session, url, max_retries=2)
        if not html:
            return []
            
        soup = BeautifulSoup(html, 'lxml')
        list_items = soup.select('.rankingnews_list li')
        
        tasks = []
        collected_count = 0
        
        for item in list_items:
            if collected_count >= 40: # 각 언론사당 40개 제한
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
            tasks.append(self._parse_article_detail(session, link, title, press_name, article_mode=article_mode))
            collected_count += 1
            
        # 상세 파싱 병렬(비동기) 실행
        if not tasks:
            return []
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # 에러 처리 및 None 필터링
        valid_results = [res for res in results if res and not isinstance(res, Exception)]
        return valid_results

    async def _crawl_headline_news(
        self,
        session: aiohttp.ClientSession,
        existing_hashes: set,
        article_mode: str = "politics"
    ) -> list:
        """
        메인 헤드라인 뉴스 수집 (많이 본 뉴스 랭킹에 오르기 전 실시간/주요 기사 포착)
        - politics: 정치 섹션 (section/100)
        - editorial: 오피니언 섹션 (section/110)
        """
        # 사설 모드일 때는 오피니언 섹션 페이지 사용
        if article_mode == "editorial":
            url = "https://news.naver.com/section/110"  # 오피니언 섹션
        else:
            url = "https://news.naver.com/section/100"  # 정치 섹션

        html = await self._fetch_html(session, url, max_retries=2)
        if not html:
            return []
            
        soup = BeautifulSoup(html, 'lxml')
        # 네이버 뉴스 메인 헤드라인 영역
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
            
            tasks.append(self._parse_article_detail(session, link, title, press_name, article_mode=article_mode))
            
        if not tasks:
            return []
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [res for res in results if res and not isinstance(res, Exception)]

    async def _crawl_daily_list_page(
        self,
        session: aiohttp.ClientSession,
        press_name: str,
        oid: str,
        date_str: str,
        existing_hashes: set,
        article_mode: str
    ) -> list:
        """언론사별 일일 기사 목록(LPOD) 전체 수집 (사설 등 랭킹에 안 뜨는 기사용)"""
        # 1. 사설 모드는 페이지 수 줄이기
        max_pages = 4 if article_mode == "editorial" else 14
        
        tasks = []
        collected_links = set()
        for page in range(1, max_pages + 1): 
            url = f"https://news.naver.com/main/list.naver?mode=LPOD&mid=sec&oid={oid}&listType=title&date={date_str}&page={page}"
            html = await self._fetch_html(session, url, max_retries=2)
            if not html:
                break
                
            soup = BeautifulSoup(html, 'lxml')
            items = soup.select('.list_body.newsflash_body li a')
            if not items:
                break
                
            for item in items:
                link = item.get('href')
                if not link or link in collected_links: continue
                collected_links.add(link)
                
                link_hash = hashlib.sha256(link.encode('utf-8')).hexdigest()
                if link_hash in existing_hashes: continue
                
                # 임시 캐시 추가
                existing_hashes.add(link_hash)
                
                title = item.get_text(strip=True)
                if not title: continue
                
                # 🔥 스마트 필터링: 사설일 확률이 0%인 기사는 본문 접속 시도조차 하지 않고 스킵 (네이버 서버 부하/속도 최적화)
                if any(keyword in title for keyword in ["[사진]", "[포토]", "[그림]", "[부고]", "[인사]", "[동정]", "[게시판]", "[날씨]", "오늘의 날씨"]):
                    continue
                
                tasks.append(self._parse_article_detail(session, link, title, press_name, article_mode=article_mode))
                
        if not tasks:
            return []
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [res for res in results if res and not isinstance(res, Exception)]

    async def run_async_crawl(
        self,
        article_mode: str = "politics",
        custom_dates: list = None
    ) -> list:
        """
        비동기 크롤러 실행 엔트리

        Args:
            article_mode: "politics" (정치 섹션) 또는 "editorial" (사설/오피니언 섹션)
            custom_dates: 수집할 날짜 목록 (YYYYMMDD 문자열 리스트).
                          None이면 오늘 기준 DAYS_TO_CRAWL일치 자동 계산.
        """
        mode_label = "사설(오피니언)" if article_mode == "editorial" else "정치"
        logger.info(f"⚡ In-memory URL Hash 캐싱 로드 중... [섹션: {mode_label}]")
        existing_hashes = self._get_existing_url_hashes()
        logger.info(f"⚡ {len(existing_hashes)}개의 URL Hash 로드 완료.")
        
        today = self._get_kst_now()
        tasks = []
        
        # 수집할 날짜 목록 결정
        if custom_dates:
            date_list = custom_dates
            logger.info(f"📅 지정 날짜 모드: {date_list}")
        else:
            date_list = [
                (today - timedelta(days=offset)).strftime("%Y%m%d")
                for offset in range(DAYS_TO_CRAWL)
            ]
            logger.info(f"📅 자동 날짜 모드 (최근 {DAYS_TO_CRAWL}일): {date_list}")
        
        # aiohttp ClientSession 생성 및 동시 요청
        async with aiohttp.ClientSession() as session:
            # 1. 헤드라인 뉴스 수집 (custom_dates가 없을 때만 실행 - 과거 날짜엔 의미 없음)
            if not custom_dates:
                tasks.append(self._crawl_headline_news(session, existing_hashes, article_mode=article_mode))
            
            # 2. 날짜별 언론사 랭킹/전체목록 페이지 수집
            for date_str in date_list:
                for press_name, oid in TARGET_PRESS_DICT.items():
                    if article_mode == "editorial":
                        # 사설은 랭킹에 안 뜨므로 일간 전체목록 스크래핑 이용
                        tasks.append(
                            self._crawl_daily_list_page(
                                session, press_name, oid, date_str,
                                existing_hashes, article_mode=article_mode
                            )
                        )
                    else:
                        tasks.append(
                            self._crawl_ranking_page(
                                session, press_name, oid, date_str,
                                existing_hashes, article_mode=article_mode
                            )
                        )
            
            logger.info(f"⚡ {len(tasks)}개의 수집 태스크 병렬 실행 시작...")
            results = await asyncio.gather(*tasks)
            
        # 2차원 리스트 플래튼
        all_news = []
        for res_list in results:
            all_news.extend(res_list)
            
        if all_news:
            logger.info(f"📄 [ScoutAgent:Crawl] 수집된 {mode_label} 기사 리스트:")
            for i, art in enumerate(all_news, 1):
                logger.info(f"   {i}. [{art['press']}] {art['title']}")
        else:
            logger.warning(f"⚠️ [ScoutAgent:Crawl] 수집된 {mode_label} 기사가 없습니다. (날짜: {date_list})")
                
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
        state에 'article_mode' 키가 있으면 해당 모드로, 없으면 기본 'politics' 모드로 실행합니다.
        """
        log_llm_event("ScoutAgent", "비동기 크롤러 노드 시작")
        
        article_mode = state.get("article_mode", "politics")
        custom_dates = state.get("custom_dates", None)
        
        # 과거 데이터 삭제
        cleanup_res = self.cleanup_old_data(state)
        cleanup_msg = cleanup_res.get("messages", [""])[0] if isinstance(cleanup_res, dict) else cleanup_res
        logger.info(f"⚡ [ScoutAgent:Crawl] {cleanup_msg}")
        
        # 비동기 실행을 위한 이벤트 루프
        import nest_asyncio
        nest_asyncio.apply()
        
        loop = asyncio.get_event_loop()
        all_news = loop.run_until_complete(
            self.run_async_crawl(article_mode=article_mode, custom_dates=custom_dates)
        )
        
        mode_label = "사설(오피니언)" if article_mode == "editorial" else "정치"
        msg = f"비동기 크롤링 완료: 총 {len(all_news)}건의 유효한 {mode_label} 기사 수집됨"
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
                image_list = art.get('image_urls', [])
                # 만약 기존 캐시나 오류로 단일 문자열이 넘어올 경우 방어 로직
                if not image_list and art.get('image_url'):
                    image_list = [art.get('image_url')]

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
