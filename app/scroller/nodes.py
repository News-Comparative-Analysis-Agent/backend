from datetime import datetime, timedelta
import time
import random
import json
import requests
import concurrent.futures
import pandas as pd
from bs4 import BeautifulSoup
import google.generativeai as genai
import os
from sqlalchemy.orm import Session
import numpy as np
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from hdbscan import HDBSCAN
from umap import UMAP
from bertopic import BERTopic
import logging
import gc
import os
from dotenv import load_dotenv

from app.scroller.repository import ScrollerRepository
from app.scroller.state import CrawlState, ClusterState
from app.core.logger import logger, log_llm_event


# .env 로드
load_dotenv()
env = os.environ

TARGET_PRESS_DICT = {
    "한겨레": "028", "경향신문": "032", 
    "조선일보": "023", "동아일보": "020", "연합뉴스": "001"
}
DAYS_TO_CRAWL = 4

# 온프레미스 LLM 서버 설정 (OpenAI 호환 API 구조)
LOCAL_LLM_SERVERS = {
    "1.5B": f"http://{env.get('LLM_SERVER_IP')}:{env.get('1.5B_PORT')}/{env.get('LLM_SERVER_API_URI')}",
    "3B":   f"http://{env.get('LLM_SERVER_IP')}:{env.get('3B_PORT')}/{env.get('LLM_SERVER_API_URI')}",
    "7B":   f"http://{env.get('LLM_SERVER_IP')}:{env.get('7B_PORT')}/{env.get('LLM_SERVER_API_URI')}",
}

class ScrollerNodes:
    """
    LangGraph의 각 단계(Node)에서 실행될 구체적인 파이썬 함수들의 집합입니다.
    네이버 뉴스 크롤링, BERTopic 군집화, Gemini AI 분석 등의 핵심 로직을 포함합니다.
    """
    
    # AI 모델(BERTopic/SBERT) 캐싱을 위한 클래스 변수 (싱글톤 패턴)
    # 수 GB의 모델을 매번 로드하지 않도록 메모리에 고정하여 사용합니다.
    _topic_model = None

    def __init__(self, db: Session):
        """
        Args:
            db (Session): 작업을 위한 데이터베이스 세션
        """
        self.repo = ScrollerRepository(db)

    def _get_kst_now(self):
        """
        한국 표준시(KST) 기준 현재 시간을 반환합니다.
        서버 환경에 상관없이 일관된 날짜 처리를 위해 사용합니다 (UTC+9 적용).
        """
        return datetime.utcnow() + timedelta(hours=9)

    def _parse_llm_json(self, text: str) -> dict:
        """
        AI가 반환한 텍스트에서 JSON 블록을 추출하여 파싱합니다.
        제미나이뿐만 아니라 로컬 LLM의 응답도 처리할 수 있도록 공통화하였습니다.
        """
        try:
            result_text = text.strip()
            # 마크다운 코드 블록 제거 로직
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].strip()
            return json.loads(result_text)
        except Exception as e:
            logger.error(f"JSON 파싱 실패: {e}\n원본 텍스트: {text}")
            return None

    def _call_local_llm(self, model_size: str, prompt: str) -> str:
        """
        온프레미스 로컬 LLM 서버에 요청을 보냅니다.
        """
        url = LOCAL_LLM_SERVERS.get(model_size)
        if not url:
            raise ValueError(f"지원하지 않는 모델 사이즈: {model_size}")
            
        payload = {
            "model": f"local-{model_size}",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1
        }
        
        try:
            log_llm_event("LocalLLM", f"Requesting {model_size}", details=f"URL: {url}\nPayload: {json.dumps(payload, ensure_ascii=False)}")
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            content = result['choices'][0]['message']['content']
            log_llm_event("LocalLLM", f"Response received from {model_size}", details=content)
            return content
        except Exception as e:
            log_llm_event("LocalLLM", f"Error: {e}", details=str(e))
            logger.error(f"로컬 LLM({model_size}) 호출 실패: {e}")
            raise e

    def _call_llm(self, prompt: str, model_size: str, state: dict) -> dict:
        """
        llm_mode에 따라 제미나이 또는 로컬 LLM을 호출합니다.
        """
        mode = state.get("llm_mode", "gemini_only")
        
        # 1. 로컬 Only 모드
        if mode == "local_only":
            content = self._call_local_llm(model_size, prompt)
            return self._parse_llm_json(content)
            
        # 2. 제미나이 Only 모드
        if mode == "gemini_only":
            return self._call_gemini(prompt)
            
        # 3. 하이브리드 모드 (로컬 우선 -> 실패 시 제미나이)
        if mode == "local_priority":
            try:
                content = self._call_local_llm(model_size, prompt)
                parsed = self._parse_llm_json(content)
                if parsed: return parsed
                raise ValueError("로컬 LLM 응답 파싱 실패")
            except Exception as e:
                logger.warning(f"로컬 LLM 실패로 인해 제미나이로 폴백합니다: {e}")
                return self._call_gemini(prompt)
        
        return self._call_gemini(prompt)

    def _call_gemini(self, prompt: str) -> dict:
        """
        제미나이 API를 호출합니다.
        """
        try:
            log_llm_event("Gemini", "Requesting gemini-2.0-flash", details=prompt)
            model = genai.GenerativeModel('gemini-2.0-flash')
            response = model.generate_content(prompt)
            log_llm_event("Gemini", "Response received", details=response.text)
            return self._parse_llm_json(response.text)
        except Exception as e:
            log_llm_event("Gemini", f"Error: {e}", details=str(e))
            logger.error(f"Gemini 호출 실패: {e}")
            return None

    # ==========================================
    # Helper: Retry Logic
    # ==========================================
    def _fetch_with_retry(self, url: str, headers: dict = None, timeout: int = 10, max_retries: int = 3):
        if not headers:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        for attempt in range(max_retries):
            try:
                res = requests.get(url, headers=headers, timeout=timeout)
                if res.status_code == 200:
                    return res
            except requests.exceptions.RequestException as e:
                logger.warning(f"⚠️ {attempt + 1}번째 시도 실패: {url} -> {e}")
                time.sleep(2)
        return None

    # ==========================================
    # Crawl Graph Nodes
    # ==========================================
    def node_clean_old_data(self, state: CrawlState) -> dict:
        """
        [Node] 오래된 기사 데이터를 정리합니다.
        기준 기간(DAYS_TO_CRAWL)보다 오래된 데이터를 삭제하여 DB 용량을 최적화합니다.
        """
        log_llm_event("cleanup", "오래된 데이터 정리 노드 시작")
        deleted_count = self.repo.delete_old_articles(days=30)
        msg = f"과거 데이터 삭제 완료: {deleted_count}건"
        log_llm_event("cleanup", msg)
        return {"messages": [msg]}

    def _get_article_detail_with_section(self, url: str):
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        try:
            res = self._fetch_with_retry(url, headers=headers, timeout=10)
            if not res: return None
            soup = BeautifulSoup(res.text, 'html.parser')
            
            section = ""
            meta_section = soup.select_one('meta[property="article:section"]')
            if meta_section:
                section = meta_section['content']
            else:
                cat_tag = soup.select_one('.media_end_categorize_item')
                if cat_tag:
                    section = cat_tag.get_text(strip=True)
            
            if section != "정치":
                return None 
                
            content_area = soup.select_one('#dic_area') or soup.select_one('#newsct_article')
            content = ""
            if content_area:
                for tag in content_area.select('.img_desc, .end_photo_org, .media_end_summary, .byline_s'):
                    tag.extract()
                content = content_area.get_text(strip=True)
                
            img_tag = soup.select_one('meta[property="og:image"]')
            image_url = img_tag['content'] if img_tag else ""
            
            date_tag = soup.select_one('.media_end_head_info_datestamp span')
            pub_date = date_tag['data-date-time'] if date_tag else ""
            
            # Extract reporter name
            reporter = ""
            reporter_tag = soup.select_one('.media_end_head_journalist_name') or soup.select_one('.byline_s')
            if reporter_tag:
                reporter = reporter_tag.get_text(strip=True).replace('기자', '').strip()

            return {
                "section": section,
                "content": content,
                "image_url": image_url,
                "pub_date": pub_date,
                "reporter": reporter
            }
        except Exception as e:
            logger.warning(f"기사 상세 수집 실패 ({url}): {e}")
            return None

    def node_crawl_news(self, state: CrawlState) -> dict:
        """
        [Node] 네이버 뉴스 랭킹 페이지에서 정치 섹션 기사를 수집합니다.
        설정된 기간 동안 주요 언론사의 기사 리스트를 훑으며 신규 기사만 수집합니다.
        """
        log_llm_event("crawl", "뉴스 수집 노드 시작")
        all_news = []
        seen_articles = set() # 한 세션 내에서의 중복 제거용
        
        today = self._get_kst_now()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        
        # 'n일' 전부터 오늘까지 루프
        for day_offset in range(DAYS_TO_CRAWL):
            target_date = today - timedelta(days=day_offset)
            date_str = target_date.strftime("%Y%m%d")
            
            # 사전에 정의된 주요 언론사별 루프
            for press_name, oid in TARGET_PRESS_DICT.items():
                url = f"https://news.naver.com/main/ranking/office.naver?officeId={oid}&date={date_str}"
                try:
                    res = self._fetch_with_retry(url, headers=headers, timeout=20)
                    if not res: continue
                    soup = BeautifulSoup(res.text, 'html.parser')
                    list_items = soup.select('.rankingnews_list li')
                    
                    if not list_items: continue

                    collected_count = 0
                    for item in list_items:
                        if collected_count >= 15: break # 언론사당 최대 15개까지만 수집
                        
                        link_tag = item.select_one('a')
                        if not link_tag: continue
                        
                        link = link_tag['href']
                        if link.startswith("/"): link = "https://news.naver.com" + link
                        
                        # 뉴스 고유 ID 추출 (중복 수집 방지)
                        try:
                            article_id = link.split("/article/")[1].split("?")[0] 
                        except:
                            article_id = link
                            
                        if article_id in seen_articles: continue
                        seen_articles.add(article_id)
                        
                        title = link_tag.get_text(strip=True)
                        # 뉴스 상세 페이지 접속하여 본문 및 섹션 확인
                        detail = self._get_article_detail_with_section(link)
                        
                        # 정치 섹션이 맞고 본문이 충분한 경우만 저장 리스트에 추가
                        if detail and len(detail['content']) > 50:
                            # DB에서 이미 수집된 기사인지 최종 확인
                            if self.repo.is_article_exists(link):
                                continue
                                
                            all_news.append({
                                "press": press_name,
                                "title": title,
                                "content": detail['content'],
                                "image_url": detail['image_url'],
                                "pub_date": detail['pub_date'],
                                "link": link,
                                "reporter": detail.get('reporter', '')
                            })
                            collected_count += 1
                        # 부하 조절을 위한 짧은 대기
                        time.sleep(random.uniform(0.05, 0.1))
                except Exception as e:
                    logger.error(f"언론사 {press_name} 크롤링 중 에러: {e}")
        
        msg = f"신규 정치 기사 {len(all_news)}건 수집됨"
        log_llm_event("crawl", msg)
        return {"raw_articles": all_news, "messages": [msg]}

    def _analyze_article_with_llm(self, title: str, content: str, state: dict) -> dict:
        """
        기사를 분석하여 요약 및 정치 성향을 도출합니다. (3B 단일 통합 호출로 단순화)
        - Gemini/Local/Hybrid 모두 통합 프롬프트를 사용하여 AI 호출 횟수를 최소화합니다.
        - 특히 bias_reason은 기사 원본 문장을 그대로 발췌하도록 강제합니다.
        """
        mode = state.get("llm_mode", "gemini_only")
        
        # 통합 분석 프롬프트 정의
        common_prompt = f"""
        다음 뉴스 기사를 분석하여 JSON 형식으로 결과를 반환해주세요.
        제목: {title}
        내용: {content[:1500]}
        
        [작성 규칙 (JSON)]
        1. "summary": 기사 내용을 3줄 이하로 요약하십시오.
        2. "bias": neutral, conservative, liberal 중 1개를 선택하십시오.
        3. "bias_score": 성향 강도 점수 (-5.0:진보 ~ 5.0:보수)를 실수 형식으로 입력하십시오.
        4. "bias_reason": 성향 점수 부여의 근거가 된 **기사 원문의 문장을 토씨 하나 틀리지 말고 그대로 추출**하십시오. 절대 요약하거나 당신의 언어로 수정하지 마십시오.

        {{
            "summary": "...",
            "bias": "...",
            "bias_score": 0.0,
            "bias_reason": "..."
        }}
        """

        # 1. 제미나이 모드 처리
        if mode == "gemini_only":
            return self._call_gemini(common_prompt)

        # 2. 로컬/하이브리드 모드 처리 (3B 단일 호출로 통합)
        try:
            # 병렬 호출 없이 3B 모델에게 모든 역할을 몰아서 요청
            parsed = self._call_llm(common_prompt, "3B", state)
            
            if parsed:
                return parsed
            
            raise ValueError("LLM 응답 파싱 빈값")

        except Exception as e:
            logger.error(f"3B 통합 분석 중 에러: {e}")
            return {
                "summary": "분석 실패",
                "bias": "neutral",
                "bias_score": 0.0,
                "bias_reason": "데이터 처리 오류"
            }

    def node_analyze_and_save(self, state: CrawlState) -> dict:
        """
        [Node] 수집된 기사들을 AI로 분석하고 데이터베이스에 저장합니다.
        메타데이터 저장과 본문 저장을 한 트랜잭션으로 처리합니다.
        """
        log_llm_event("analyze_save", "기사 분석 및 저장 노드 시작")
        raw_news = state.get("raw_articles", [])
        df_unique = pd.DataFrame(raw_news)
        
        saved_count = 0
        skipped_count = 0
        
        if df_unique.empty:
            return {"saved_count": 0, "skipped_count": 0, "messages": ["수집된 새 기사가 없어 분석 생략"]}

        # 수집된 각 기사에 대해 루프 실행
        for _, row in df_unique.iterrows():
            try:
                # 1. 언론사 객체 획득 (없으면 생성)
                publisher = self.repo.get_or_create_publisher(row['press'])
                
                # 2. 실시간 중복 체크 (다시 한 번 검증)
                if self.repo.is_article_exists(row['link']):
                    skipped_count += 1
                    continue
                
                try:
                    pub_dt = pd.to_datetime(row['pub_date'])
                except:
                    pub_dt = self._get_kst_now()
                    
                # 3. AI 분석 수행 (요약, 정치 성향 파악) - 멀티 LLM 연동 버전
                ai_data = self._analyze_article_with_llm(row['title'], row['content'], state)
                if not ai_data:
                    ai_data = {"summary": "분석 실패", "bias": "neutral", "bias_score": 0.0, "bias_reason": "API 응답 부재"}
                
                try:
                    bias_score_val = float(ai_data.get('bias_score', 0.0))
                except:
                    bias_score_val = 0.0
                
                # 4. DB 저장
                self.repo.save_article_with_body(
                    publisher_id=publisher.id,
                    title=row['title'],
                    url=row['link'],
                    image_urls=[row['image_url']] if row.get('image_url') else [],
                    published_at=pub_dt,
                    content=row['content'],
                    summary=ai_data.get('summary'),
                    bias=ai_data.get('bias'),
                    bias_score=bias_score_val,
                    reporter=row.get('reporter', '')
                )
                saved_count += 1
            except Exception as e:
                logger.error(f"기사 저장 중 에러 ({row.get('link')}): {e}")
                self.repo.db.rollback() 
                
        self.repo.db.commit() 
        msg = f"AI 분석 및 저장 완료: {saved_count}건"
        log_llm_event("analyze_save", msg)
        return {
            "saved_count": saved_count, 
            "skipped_count": skipped_count,
            "messages": [msg]
        }

    # ==========================================
    # Cluster Graph Nodes
    # ==========================================
    def node_fetch_unclustered(self, state: ClusterState) -> dict:
        log_llm_event("fetch", "미분류 기사 로드 노드 시작")
        try:
            # 이전 단계(크롤링 등)에서 예외 처리되지 않은 트랜잭션 오류가 남아있을 경우를 대비해 롤백 수행
            self.repo.db.rollback()
            
            unclustered_articles = self.repo.get_unclustered_articles()
            data = []
            for a in unclustered_articles:
                content = a.body.raw_content if hasattr(a, 'body') and a.body else ""
                data.append({
                    'article_id': a.id,
                    'title': a.title,
                    'content': content,
                    'pub_date': a.published_at,
                    'link': a.url
                })
            msg = f"미분류 기사 {len(data)}건 로드됨"
            log_llm_event("fetch", msg)
            return {"unclustered_articles": data, "messages": [msg]}
        except Exception as e:
            self.repo.db.rollback()
            msg = f"미분류 기사 로드 실패: {e}"
            log_llm_event("fetch", msg, type="ERROR")
            return {"unclustered_articles": [], "error": str(e), "messages": [msg]}

    def _remove_duplicates_fast(self, df: pd.DataFrame, threshold: float = 0.90) -> pd.DataFrame:
        if df.empty: return df
        tfidf = TfidfVectorizer(max_features=1000).fit_transform(df['content'].str[:300].fillna(''))
        duplicates = set()
        batch_size = 500
        num_docs = len(df)
        
        for i in range(0, num_docs, batch_size):
            batch_end = min(i + batch_size, num_docs)
            similarities = cosine_similarity(tfidf[i:batch_end], tfidf)
            for local_idx in range(batch_end - i):
                global_idx = i + local_idx
                if global_idx in duplicates: continue
                target_indices = np.where(similarities[local_idx, global_idx+1:] > threshold)[0]
                duplicates.update(target_indices + (global_idx + 1))
                
        return df.drop(index=list(duplicates)).copy()
            

    def _get_topic_model(self):
        """BERTopic 모델 싱글톤 반환 (지연 로딩)"""
        if ScrollerNodes._topic_model is not None:
            return ScrollerNodes._topic_model

        logger.info("🤖 BERTopic 모델 및 임베딩 로드 시작 (첫 실행시에만 수행)...")
        
        korean_stopwords = [
            "뉴스", "종합", "속보", "기자", "특파원", "위해", "밝혔다", "대해", "관련", 
            "오늘", "오후", "오전", "것으로", "따르면", "있는", "했다", "말했다",
            "민주당", "국민의힘", "의원", "대통령", "대표", "정부", "국회", "여야",
            "국민", "라며", "대한", "상황", "입장", "발언", "논란", "한국", "우리",
            "이재명", "윤석열", "한동훈", "장관", "수사", "주장", "평가", "문제", "이유",
            "이날", "예정", "시간", "최근", "다시", "크게", "이후", "통해", "사실"
        ]
        
        vectorizer = CountVectorizer(stop_words=korean_stopwords, ngram_range=(1, 2))
        umap_model = UMAP(n_neighbors=5, n_components=10, min_dist=0.0, metric='cosine', random_state=42)
        hdbscan_model = HDBSCAN(min_cluster_size=5, min_samples=2, metric='euclidean', cluster_selection_method='eom', prediction_data=True, cluster_selection_epsilon=0.3)
        
        ScrollerNodes._topic_model = BERTopic(
            embedding_model="snunlp/KR-SBERT-V40K-klueNLI-augSTS",
            vectorizer_model=vectorizer,
            umap_model=umap_model,
            hdbscan_model=hdbscan_model,   
            nr_topics="auto", 
            calculate_probabilities=True,
            verbose=False
        )
        logger.info("✅ BERTopic 모델 로드 완료.")
        return ScrollerNodes._topic_model

    def node_bertopic_cluster(self, state: ClusterState) -> dict:
        """
        [Node] 수집된 미분류 기사들을 의미론적 유사도 기반으로 군집화(Clustering)합니다.
        BERTopic 알고리즘을 사용하여 문서 간의 주제를 식별합니다.
        """
        log_llm_event("cluster", "클러스터링 노드 시작")
        articles = state.get("unclustered_articles", [])
        # 최소 10개의 기사가 있어야 분석이 가능하도록 제한
        if len(articles) < 10:
            return {"clustered_topics": [], "messages": ["분석할 기사가 너무 적어(10개 미만) 클러스터링 건너뜜"]}

        df = pd.DataFrame(articles)
        # 고속 중복 제거 수행 (의미가 90% 일치하는 기사 제거)
        df_clean = self._remove_duplicates_fast(df)

        if len(df_clean) < 10:
            return {"clustered_topics": [], "messages": ["중복 제거 후 기사가 너무 적어 건너뜀"]}
            
        try:
            # 1. AI 모델 인스턴스 획득 (싱글톤)
            topic_model = self._get_topic_model()
            
            # 2. 입력 데이터 준비: 제목을 반복하여 가중치를 높이고 본문 500자까지 포함
            docs = [f"{str(t)} {str(t)} {str(c)[:500]}" for t, c in zip(df_clean['title'], df_clean['content'])]
            
            logger.info(f"📊 {len(docs)}건 기사 클러스터링 시작...")
            # 3. 실제 군집화 연산 수행 (가장 자원을 많이 소모하는 단계)
            topics, _ = topic_model.fit_transform(docs)
            
            df_clean['topic_id'] = topics
            topic_info = topic_model.get_topic_info()
            
            # 4. 유효 토픽(Outlier가 아닌 토픽) 추출
            top_topics = topic_info[topic_info['Topic'] != -1].copy() 

            clustered_topics = []
            for _, row in top_topics.iterrows():
                topic_id = row['Topic']
                count = row['Count']
                
                # 기사가 5개 미만인 작은 군집은 의미 있는 이슈로 보지 않고 건너뜀
                if count < 5: continue

                topic_indices = df_clean[df_clean['topic_id'] == topic_id].index
                topic_articles = df_clean.loc[topic_indices]
                
                clustered_topics.append({
                    "topic_id": topic_id,
                    "count": count,
                    "titles": topic_articles['title'].tolist(),
                    "article_ids": topic_articles['article_id'].tolist()
                })

            # 5. 메모리 최적화 작업: 연산에 사용된 대규모 리스트 해제 및 가비지 컬렉션 강제 실행
            del docs
            gc.collect()

            return {"clustered_topics": clustered_topics, "messages": [f"BERTopic 결과 {len(clustered_topics)}개 이슈 그룹 발견"]}
            
        except Exception as e:
            msg = f"클러스터링 실패: {e}"
            log_llm_event("cluster", msg, type="ERROR")
            logger.error(f"클러스터링 실행 중 치명적 에러: {e}")
            return {"clustered_topics": [], "messages": [msg]}

    def _generate_issue_details_with_llm(self, titles: list, state: dict):
        """
        이슈 그룹에 대해 제목과 배경 설명을 생성합니다.
        3B 모델 또는 제미나이를 사용합니다.
        """
        try:
            prompt = f"""
            다음은 동일한 뉴스 사건에 대한 기사 제목들입니다:
            {titles[:10]} (총 {len(titles)}건)

            이 뉴스들을 분석하여 구체적인 단일 이슈에 대한 제목, 요약, 발단, 주요 쟁점을 작성해주세요.
            
            [작성 규칙]
            1. 반드시 아래와 같은 JSON 형식으로만 응답할 것 (백틱이나 markdown 서식 없이 순수 JSON 텍스트만 출력).
            {{
                "title": "15자 이내의 구체적인 이슈 제목",
                "description": "이슈의 배경과 핵심 내용을 포함한 3~4문장의 요약",
                "background": "이 이슈가 발생하게 된 핵심 발단 또는 배경 설명 (1~2문장)",
                "core_contentions": "이 이슈와 관련된 주요 쟁점이나 갈등 또는 찬반 의견 (1~2문장)"
            }}
            2. 🚨 [매우 중요] '정치 현안', '주요 이슈', '정치권 소식', '여야 대립' 같은 포괄적이고 뭉뚱그려진 제목은 절대 금지합니다.
            3. 기사에 등장하는 '특정 인물', '특정 정책', '사건'이 제목에 명확히 드러나야 합니다.
            4. 제목은 명사형으로 끝맺을 것.
            """
            parsed = self._call_llm(prompt, "3B", state)
            
            if parsed:
                return (
                    parsed.get("title", titles[0]), 
                    parsed.get("description", "이슈 요약이 제공되지 않았습니다."),
                    parsed.get("background", "배경 정보 없음"),
                    parsed.get("core_contentions", "주요 쟁점 정보 없음")
                )
            
            return titles[0], "요약 생성 실패", "배경 정보 없음", "주요 쟁점 정보 없음"
        except Exception as e:
            logger.error(f"이슈 제목 생성 실패: {e}")
            return titles[0], "요약 생성 실패", "배경 정보 없음", "주요 쟁점 정보 없음"

    def node_name_and_save_issues(self, state: ClusterState) -> dict:
        log_llm_event("name_and_save", "이슈 명명 및 저장 노드 시작")
        topics = state.get("clustered_topics", [])
        saved_issue_count = 0
        
        if not topics:
            return {"saved_issue_count": 0, "messages": ["저장할 이슈 토픽이 없습니다."]}

        try:
            for t in topics:
                titles = t["titles"]
                count = t["count"]
                article_ids = t["article_ids"]
                
                time.sleep(1.0) 
                ai_label, description, background, core_contentions = self._generate_issue_details_with_llm(titles, state)
                
                self.repo.save_issue_and_relations(
                    ai_label=ai_label,
                    description=description,
                    count=count,
                    article_ids_to_update=article_ids,
                    background=background,
                    core_contentions=core_contentions,
                    media_ratio=None # 언론사 비율은 API에서 실시간 계산하도록 권장하여 일단 빈 값으로 둡니다
                )
                saved_issue_count += 1
                
            self.repo.db.commit()
            msg = f"이슈 매핑 파이프라인 종료: {saved_issue_count}개 생성 완료"
            log_llm_event("name_and_save", msg)
            return {"saved_issue_count": saved_issue_count, "messages": [msg]}
            
        except Exception as e:
            self.repo.db.rollback()
            msg = f"저장 중 에러: {e}"
            log_llm_event("name_and_save", msg, type="ERROR")
            return {"saved_issue_count": 0, "error": str(e), "messages": [msg]}
