import os
import asyncio
import aiohttp
import hashlib
import random
# feedparser는 더 이상 사용하지 않으므로 제거
import pytz
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
    "한국일보": "469", "국민일보": "005", "서울신문": "081", "세계일보": "022"
}
DAYS_TO_CRAWL = 3

# 사설 검색용 복합 쿼리 (특례 기호 사이에 공백 필수: Naver API 제약사항)
EDITORIAL_SEARCH_QUERIES = {
    "조선일보": "조선일보 ([사설] | [칼럼] | [만물상] | [팔면봉] | [태평로])",
    "동아일보": "동아일보 ([사설] | [칼럼] | [횡설수설] | [오늘과내일])", 
    "한겨레":   "한겨레 ([사설] | [칼럼] | [유레카])",
    "경향신문": "경향신문 ([사설] | [칼럼] | [여적])",
    "중앙일보": "중앙일보 ([사설] | [칼럼] | [분수대] | [시시각각])",
    "한국일보": "한국일보 [사설]",
    "국민일보": "국민일보 ([사설] | [칼럼] | [여의춘추] | [한마당])",
    "서울신문": "서울신문 ([사설] | [칼럼] | [씨줄날줄])",
    "세계일보": "세계일보 ([사설] | [칼럼] | [설왕설래])",
    "문화일보": "문화일보 ([사설] | [칼럼] | [오후여담])",
}

# 네이버 검색 API 설정
NAVER_SEARCH_URL = "https://openapi.naver.com/v1/search/news.json"
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "YOUR_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "YOUR_CLIENT_SECRET")

# 사설/오피니언 필터링용 섹션 이름 (EUC-KR 등 인코딩 대응)
EDITORIAL_SECTIONS = {"오피니언", "사설", "칼럼", "opinion", "editorial", "社說"}

# [최적화] 검색 API는 리스트 누락 보충용(Safety Net)으로 활용

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
        
        # 🔥 메타 페이지(랭킹, 목록) 전용 세마포어
        self.meta_semaphore = asyncio.Semaphore(5)
        
        # 🔥 언론사별 기사 본문 동시 요청 제한 (디도스 방어 회피용: 언론사당 최대 3개)
        self.press_semaphores = {
            oid: asyncio.Semaphore(3) 
            for oid in TARGET_PRESS_DICT.values()
        }

        # 🔥 [안정화] 전역 기사 본문 수집 세마포어 (네이버 전체 부하 제어: 최대 10개)
        self.article_semaphore = asyncio.Semaphore(10)

    def _get_kst_now(self) -> datetime:
        """현재 KST(한국 표준시) 기준 일시 반환"""
        return datetime.now(pytz.utc).astimezone(pytz.timezone('Asia/Seoul')).replace(tzinfo=None)

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
        """단일 URL에 비동기 GET 요청 수행 (안정성 강화 버전)"""
        for attempt in range(max_retries):
            try:
                # [안정화] 타임아웃을 20초 -> 40초로 확대하여 지연 대응
                timeout_settings = aiohttp.ClientTimeout(total=40, connect=10, sock_read=30)
                async with session.get(url, headers=self.headers, timeout=timeout_settings) as resp:
                    if resp.status == 200:
                        content_bytes = await resp.read()
                        # 인코딩 감지 및 디코딩 (errors='replace'로 깨짐 방지)
                        return content_bytes.decode(resp.charset or 'utf-8', errors='replace')
                    elif resp.status == 429:
                        wait_time = 5 * (attempt + 1) + random.uniform(1, 3)
                        logger.warning(f"🚨 [ScoutAgent] 429 Rate Limit 발생. {wait_time:.1f}초 대기 후 재시도: {url}")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.warning(f"⚠️ [ScoutAgent] HTTP {resp.status} 에러: {url}")
            except asyncio.TimeoutError:
                logger.warning(f"⌛ [ScoutAgent] 타임아웃 발생 (시도 {attempt+1}/{max_retries}): {url}")
            except Exception as e:
                logger.error(f"❌ [ScoutAgent] HTTP 요청 에러 ({url}): {e}")
                
            await asyncio.sleep(random.uniform(1, 2)) # 실패 시 약간 대기
        return None

    async def _fetch_meta_html(self, session: aiohttp.ClientSession, url: str, max_retries=2) -> str:
        """목록/랭킹 페이지용 래퍼 함수 (메타 페이지 전용 meta_semaphore 적용)"""
        async with self.meta_semaphore:
            return await self._fetch_html(session, url, max_retries)

    async def _parse_article_detail(
        self,
        session: aiohttp.ClientSession,
        link: str,
        title: str,
        press_name: str,
        article_mode: str = "politics"
    ) -> dict:
        """
        기사 상세 페이지를 비동기로 파싱 (언론사별 세마포어 적용)
        """
        # OID 추출해서 언론사별 세마포어 적용
        oid = TARGET_PRESS_DICT.get(press_name)
        press_sem = self.press_semaphores.get(oid)
        
        if press_sem:
            async with press_sem:
                # [안정화] 언론사 세마포어 안에서 전역 세마포어를 한 번 더 체크하여 전체 부하 조절
                async with self.article_semaphore:
                    return await self._parse_with_delay(session, link, title, press_name, article_mode)
        
        async with self.article_semaphore:
            return await self._parse_with_delay(session, link, title, press_name, article_mode)

    async def _parse_with_delay(
        self,
        session: aiohttp.ClientSession,
        link: str,
        title: str,
        press_name: str,
        article_mode: str
    ) -> dict:
        # 요청 간 랜덤 딜레이 추가 (봇 차단 회피)
        await asyncio.sleep(random.uniform(0.3, 0.8))
        
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
        
        # 제목 기반 사설 전용 필터 (오피니언 섹션 내 [포럼], [시론] 등 일반 칼럼 제외)
        # ✅ 허용 패턴: 제목 앞/뒤에 [사설] 또는 한자 표기(社說)가 붙는 기사만 수집
        EDITORIAL_TITLE_KEYWORDS = [
            "[사설]",   # 표준 표기: [사설] 제목...
            "사설]",    # 불완전 태그 방어: 사설] 제목... (일부 언론사 오표기 대응)
            "[社說]",   # 한자 표기: [社說] 제목...
            "社說]",    # 한자 불완전 태그 방어
        ]
        is_editorial_title = any(kw in title for kw in EDITORIAL_TITLE_KEYWORDS)
        
        if article_mode == "editorial" and not is_editorial_title:
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
        html = await self._fetch_meta_html(session, url, max_retries=2)
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
        # 에러 처리 및 None 필터링 (예외 발생 시 명시적 로깅)
        for res in results:
            if isinstance(res, Exception):
                logger.warning(f"⚠️ [ScoutAgent:RankingPage] 기사 파싱 중 예외 발생: {res}")
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
        # 메타 페이지 전용 래퍼 호출
        html = await self._fetch_meta_html(session, url, max_retries=2)
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
        for res in results:
            if isinstance(res, Exception):
                logger.warning(f"⚠️ [ScoutAgent:HeadlineNews] 기사 파싱 중 예외 발생: {res}")
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
        """언론사별 일일 기사 목록(LPOD) 수집 (병합 및 최적화 버전)"""
        # 1. 모드별 페이지 수 및 필터 설정
        max_pages = 4 if article_mode == "editorial" else 14
        sid_param = "&sid1=110" if article_mode == "editorial" else ""
        
        # 페이지 URL 목록 생성
        page_urls = [
            f"https://news.naver.com/main/list.naver?mode=LPOD&mid=sec&oid={oid}&listType=title&date={date_str}&page={p}{sid_param}"
            for p in range(1, max_pages + 1)
        ]
        
        # 2. 페이지 목록 병렬 수집
        page_htmls = await asyncio.gather(*[self._fetch_meta_html(session, url) for url in page_urls])
        
        tasks = []
        collected_links = set()
        
        for html in page_htmls:
            if not html:
                continue
                
            soup = BeautifulSoup(html, 'lxml')
            # 리스트 타입(title)일 때의 셀렉터 대응 강화
            items = soup.select('.list_body.newsflash_body li a') or soup.select('.list_body ul li a')
            if not items:
                continue
                
            for item in items:
                link = item.get('href')
                if not link or link in collected_links: continue
                
                # 비기사성 URL(공지 등) 제외
                if "article" not in link: continue
                collected_links.add(link)
                
                link_hash = hashlib.sha256(link.encode('utf-8')).hexdigest()
                if link_hash in existing_hashes: continue
                
                existing_hashes.add(link_hash)
                title = item.get_text(strip=True)
                if not title: continue
                
                # 노이즈 필터링 확장
                if any(kw in title for kw in ["[사진]", "[포토]", "[그림]", "[부고]", "[인사]", "[동정]", "[게시판]", "[날씨]", "오늘의 날씨"]):
                    continue
                
                tasks.append(self._parse_article_detail(session, link, title, press_name, article_mode=article_mode))
                
        if not tasks:
            return []
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                logger.warning(f"⚠️ [ScoutAgent:DailyListPage] 기사 파싱 중 예외 발생: {res}")
        return [res for res in results if res and not isinstance(res, Exception)]

    async def _crawl_editorial_via_search(
        self,
        session: aiohttp.ClientSession,
        press_name: str,
        query: str,
        existing_hashes: set,
        date_str: str
    ) -> list:
        """네이버 뉴스 검색 API를 사용해 사설/칼럼 전문 수집 (옵션 B 전면 개편)"""
        headers = {
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        }
        params = {
            "query": query,
            "display": 20,  # 사설+칼럼 병합 커버를 위해 충분히 확보
            "sort": "date",
        }

        try:
            # Naver Search API는 Burst 요청에 매우 민감하므로 추가적인 랜덤 지연 삽입
            await asyncio.sleep(random.uniform(0.3, 0.8))
            
            async with self.meta_semaphore:
                async with session.get(
                    NAVER_SEARCH_URL,
                    headers=headers,
                    params={**params, "sort": "date", "display": 100}, # 최근 기사 우선 및 개수 확대
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"⚠️ [{press_name}] 검색 API 오류: {resp.status}")
                        return []
                    data = await resp.json()
        except Exception as e:
            logger.error(f"❌ [{press_name}] 검색 API 기사 수집 실패: {e}")
            return []

        items = data.get('items', [])
        tasks = []
        from email.utils import parsedate_to_datetime
        KST = pytz.timezone('Asia/Seoul')

        for item in items:
            pub_date = item.get('pubDate', '')
            link = item.get('originallink') or item.get('link', '')
            raw_title = item.get('title', '')
            title = BeautifulSoup(raw_title, 'lxml').get_text()

            try:
                # [안정화] Naver API는 UTC를 반환하므로 KST로 변환 후 날짜 비교
                dt = parsedate_to_datetime(pub_date)
                dt_kst = dt.astimezone(KST)
                item_date = dt_kst.strftime("%Y%m%d")
                if item_date != date_str:
                    continue
            except Exception:
                continue

            if not link or not title:
                continue

            # [노이즈 필터링 고도화]
            press_match = False
            # 1. 제목에 언론사명이 포함된 경우 (기본)
            if press_name in title:
                press_match = True
            
            # 2. 도메인 매칭
            domain_map = {
                "조선일보": "chosun.com", "동아일보": "donga.com", "한겨레": "hani.co.kr",
                "경향신문": "khan.co.kr", "중앙일보": "joongang.co.kr", "한국일보": "hankookilbo.com",
                "국민일보": "kmib.co.kr", "서울신문": "seoul.co.kr", "세계일보": "segye.com", "문화일보": "munhwa.com"
            }
            target_domain = domain_map.get(press_name)
            if target_domain and target_domain in link:
                press_match = True
            
            # 3. 네이버 기사인 경우 OID로 정확하게 판별 (제목에 언론사명이 없을 때 대비)
            oid = TARGET_PRESS_DICT.get(press_name)
            if "naver.com" in link and oid and f"/{oid}/" in link:
                press_match = True

            if not press_match:
                continue

            link_hash = hashlib.sha256(link.encode()).hexdigest()
            if link_hash in existing_hashes:
                continue
            existing_hashes.add(link_hash)

            logger.info(f"🔎 [Search Hit] {press_name}: {title[:30]}...")

            if 'naver.com' in link:
                tasks.append(
                    self._parse_article_detail(
                        session, link, title, press_name, article_mode="editorial"
                    )
                )
            else:
                tasks.append(
                    self._parse_direct_editorial(session, link, title, press_name)
                )

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                logger.warning(f"⚠️ [ScoutAgent:EditorialSearch] 기사 파싱 중 예외 발생: {res}")
        return [r for r in results if r and not isinstance(r, Exception)]



    async def _parse_direct_editorial(
        self,
        session: aiohttp.ClientSession,
        link: str,
        title: str,
        press_name: str
    ) -> dict:
        """자체 사이트 기사 본문 파싱 (세마포어 래퍼 적용)"""
        oid = TARGET_PRESS_DICT.get(press_name)
        press_sem = self.press_semaphores.get(oid)
        
        if press_sem:
            async with press_sem:
                async with self.article_semaphore:
                    return await self._parse_direct_editorial_core(session, link, title, press_name)
        else:
            async with self.article_semaphore:
                return await self._parse_direct_editorial_core(session, link, title, press_name)

    async def _parse_direct_editorial_core(
        self,
        session: aiohttp.ClientSession,
        link: str,
        title: str,
        press_name: str
    ) -> dict:
        """실제 파싱 로직"""
        # 자체 서버 부하 및 봇 탐지 완벽 회피를 위해 대기 시간 대폭 증가
        await asyncio.sleep(random.uniform(3.0, 5.0))  
        
        # 자체 사이트는 네이버 헤더와 속도가 다르므로 fetch 래퍼 안쓰고 직접 때릴수도 있지만, 우선 _fetch_html 재사용
        html = await self._fetch_html(session, link)
        if not html:
            return None

        soup = BeautifulSoup(html, 'lxml')
        content = ""

        if press_name == "조선일보":
            # 조선닷컴(SPA)은 HTML DOM 텍스트가 비어있고 Fusion.globalContent JSON 안에 본문이 존재함.
            import re
            import json
            for s in soup.find_all('script'):
                if s.string and 'Fusion.globalContent' in s.string:
                    # JSON 객체 전체를 greedy하게 매칭 (non-greedy는 중간의 ; 에서 잘리는 버그 있음)
                    match = re.search(r'Fusion\.globalContent\s*=\s*(\{.+\});', s.string, re.DOTALL)
                    if match:
                        try:
                            data = json.loads(match.group(1))
                            elements = data.get('content_elements', [])
                            for el in elements:
                                if el.get('type') == 'text' and el.get('content'):
                                    # 내부 HTML 태그(<p>, <br> 등) 제거
                                    raw_text = el.get('content')
                                    clean_text = BeautifulSoup(raw_text, 'html.parser').get_text(strip=True)
                                    content += clean_text + "\n"
                        except Exception as e:
                            logger.error(f"❌ [조선일보] JSON 파싱 에러: {e}")
                    break

        elif press_name == "한국일보":
            # 한국일보 본문 셀렉터 보강
            area = (
                soup.select_one('.article-body-wrap')
                or soup.select_one('.view-content')
                or soup.select_one('.article-body')
                or soup.select_one('#article-view-content-div')
                or soup.select_one('.news-contents')
            )
            if area:
                for tag in area.select('figure, .ad, script, style, .related-news, .article-img-caption'):
                    tag.extract()
                content = area.get_text(strip=True)

        if len(content) < 50:
            return None

        # 날짜 파싱
        pub_date = ""
        date_meta = (
            soup.select_one('meta[property="article:published_time"]')
            or soup.select_one('meta[name="article:published_time"]')
        )
        if date_meta:
            pub_date = date_meta.get('content', '')

        # 썸네일
        image_urls = []
        og_img = soup.select_one('meta[property="og:image"]')
        if og_img and og_img.get('content'):
            image_urls.append(og_img['content'])

        logger.info(f"✅ [{press_name}] 자체사이트 사설 본문 수집 성공!: {title[:40]}")
        return {
            "press": press_name,
            "title": title,
            "content": content,
            "image_urls": image_urls,
            "pub_date": pub_date,
            "reporter": "",
            "link": link
        }

    async def run_async_crawl(
        self,
        article_mode: str = "editorial",
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
            final_results = []
            
            # 1. 헤드라인 뉴스 수집 (custom_dates가 없을 때만 실행)
            if not custom_dates:
                headline_tasks = [self._crawl_headline_news(session, existing_hashes, article_mode=article_mode)]
                res = await asyncio.gather(*headline_tasks, return_exceptions=True)
                for r in res:
                    if r and not isinstance(r, Exception): final_results.extend(r)
            
            # 2. 날짜별 언론사 수집 (안정화를 위해 날짜 단위로 순차 실행)
            for date_str in date_list:
                tasks = []
                logger.info(f"⏳ [{date_str}] 날짜 수집 시작...")
                
                if article_mode == "editorial":
                    # [하이브리드] 1. 네이버 LPOD 리스트 수집 (12개 전 언론사 대상)
                    # 조선/한국일보도 리스트에 기사가 노출되므로 무조건 수행 (검색 API보다 정확함)
                    for press_name, oid in TARGET_PRESS_DICT.items():
                        tasks.append(
                            self._crawl_daily_list_page(
                                session, press_name, oid, date_str,
                                existing_hashes, article_mode=article_mode
                            )
                        )
                    
                    # [하이브리드] 2. 검색 API 보충 수집 (조선/한국 등 리스트 누락 방어용)
                    for p_name in ["조선일보", "한국일보"]:
                        query = EDITORIAL_SEARCH_QUERIES.get(p_name)
                        if query:
                            tasks.append(
                                self._crawl_editorial_via_search(
                                    session, p_name, query,
                                    existing_hashes, date_str
                                )
                            )
                # else:
                #     # ⚠️ [비활성화] 정치 일반 기사 수집 모드
                #     # 현재는 사설(editorial) 모드만 운영하므로 임시 비활성화.
                #     # 복원 시 아래 주석을 해제하고 'else:'와 들여쓰기를 원복하세요.
                #     for press_name, oid in TARGET_PRESS_DICT.items():
                #         tasks.append(
                #             self._crawl_ranking_page(
                #                 session, press_name, oid, date_str,
                #                 existing_hashes, article_mode=article_mode
                #             )
                #         )
                
                if tasks:
                    logger.info(f"   ⚡ [{date_str}] {len(tasks)}개 태스크 병렬 실행...")
                    day_results = await asyncio.gather(*tasks, return_exceptions=True)
                    for d_res in day_results:
                        if isinstance(d_res, Exception):
                            logger.warning(f"⚠️ [ScoutAgent:RunCrawl] 날짜 [{date_str}] 태스크 실행 중 예외 발생: {d_res}")
                        elif d_res:
                            final_results.extend(d_res)
                            
                # 날짜 간 짧은 휴식 (차단 회피)
                await asyncio.sleep(random.uniform(1, 2))
            
        if final_results:
            logger.info(f"📄 [ScoutAgent:Crawl] 수집 완료: 총 {len(final_results)}건")
        else:
            logger.warning(f"⚠️ [ScoutAgent:Crawl] 수집된 {mode_label} 기사가 없습니다. (날짜: {date_list})")
                
        return final_results

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
        
        article_mode = state.get("article_mode", "editorial")
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
                    published_at=art.get('pub_date') if art.get('pub_date') else datetime.now(pytz.utc).astimezone(pytz.timezone('Asia/Seoul')).replace(tzinfo=None),
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
