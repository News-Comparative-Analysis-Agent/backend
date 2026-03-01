from datetime import datetime, timedelta
import time
import random
import json
import requests
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

from app.scroller.repository import ScrollerRepository
from app.scroller.state import CrawlState, ClusterState

TARGET_PRESS_DICT = {
    "한겨레": "028", "경향신문": "032", 
    "조선일보": "023", "동아일보": "020", "연합뉴스": "001"
}
DAYS_TO_CRAWL = 4

class ScrollerNodes:
    def __init__(self, db: Session):
        self.repo = ScrollerRepository(db)

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
                print(f"⚠️ {attempt + 1}번째 시도 실패: {url} -> {e}")
                time.sleep(2)
        return None

    # ==========================================
    # Crawl Graph Nodes
    # ==========================================


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
        except Exception:
            return None

    def node_crawl_news(self, state: CrawlState) -> dict:
        all_news = []
        seen_articles = set()
        try:
            try:
                res_time_req = self._fetch_with_retry('https://worldtimeapi.org/api/timezone/Asia/Seoul', timeout=5)
                if res_time_req:
                    res_time = res_time_req.json()
                    today = datetime.fromisoformat(res_time['datetime'].split('+')[0])
                else:
                    today = datetime.now()
            except Exception:
                today = datetime.now()
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            
            for day_offset in range(DAYS_TO_CRAWL):
                target_date = today - timedelta(days=day_offset)
                date_str = target_date.strftime("%Y%m%d")
                
                for press_name, oid in TARGET_PRESS_DICT.items():
                    url = f"https://news.naver.com/main/ranking/office.naver?officeId={oid}&date={date_str}"
                    try:
                        res = self._fetch_with_retry(url, headers=headers, timeout=10)
                        if not res: continue
                        soup = BeautifulSoup(res.text, 'html.parser')
                        list_items = soup.select('.rankingnews_list li')
                        
                        if not list_items: continue

                        collected_count = 0
                        for item in list_items:
                            if collected_count >= 15: break 
                            
                            link_tag = item.select_one('a')
                            if not link_tag: continue
                            
                            link = link_tag['href']
                            if link.startswith("/"): link = "https://news.naver.com" + link
                            
                            try:
                                article_id = link.split("/article/")[1].split("?")[0] 
                            except:
                                article_id = link
                                
                            if article_id in seen_articles: continue
                            seen_articles.add(article_id)
                            
                            title = link_tag.get_text(strip=True)
                            detail = self._get_article_detail_with_section(link)
                            
                            if detail and len(detail['content']) > 50:
                                # DB 중복 체크 (AI 분석 전 스킵용)
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
                            time.sleep(random.uniform(0.05, 0.1))
                    except Exception as e:
                        print(f"Error crawling {press_name} items: {e}")
                        self.repo.db.rollback()
                        
            return {"raw_articles": all_news, "messages": [f"신규 정치 기사 {len(all_news)}건 수집됨"]}
        except Exception as e:
            self.repo.db.rollback()
            return {"raw_articles": [], "error": str(e), "messages": [f"뉴스 크롤링 중 치명적 오류: {e}"]}

    def _analyze_article_with_gemini(self, title: str, content: str) -> dict:
        try:
            model = genai.GenerativeModel('gemini-2.0-flash')
            prompt = f"""
            다음 뉴스 기사를 분석하여 JSON 형식으로 결과를 반환해주세요.
            
            [기사 정보]
            제목: {title}
            내용: {content[:1500]}
            
            [작성 규칙]
            반드시 아래 구조의 순수 JSON 형식으로만 응답할 것 (백틱이나 추가 설명 금지).
            {{
                "summary": "기사의 주요 내용을 3줄 이하로 요약",
                "bias": "정치 성향 (neutral, conservative, liberal 중 1개 선택)",
                "bias_score": 성향 강도 점수 (0.0에서 10.0 사이의 실수. 완벽한 중도는 0.0, 성향이 극단적일수록 10.0에 가깝게 부여)
            }}
            """
            response = model.generate_content(prompt)
            result_text = response.text.strip()
            if result_text.startswith("```json"):
                result_text = result_text[7:-3].strip()
            return json.loads(result_text)
        except Exception as e:
            return {
                "summary": "AI 요약 실패",
                "bias": "neutral",
                "bias_score": 0.0
            }

    def node_analyze_and_save(self, state: CrawlState) -> dict:
        try:
            raw_news = state.get("raw_articles", [])
            df_unique = pd.DataFrame(raw_news)
            
            saved_count = 0
            skipped_count = 0
            
            if df_unique.empty:
                return {"saved_count": 0, "skipped_count": 0, "messages": ["수집된 새 기사가 없어 분석 생략"]}

            for _, row in df_unique.iterrows():
                try:
                    publisher = self.repo.get_or_create_publisher(row['press'])
                    
                    # 중복 체크
                    if self.repo.is_article_exists(row['link']):
                        skipped_count += 1
                        continue
                    
                    try:
                        pub_dt = pd.to_datetime(row['pub_date'])
                    except:
                        pub_dt = datetime.now()
                        
                    time.sleep(1.0) # Rate limit 방어
                    ai_data = self._analyze_article_with_gemini(row['title'], row['content'])
                    
                    try:
                        bias_score_val = float(ai_data.get('bias_score', 0.0))
                    except:
                        bias_score_val = 0.0
                        
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
                except Exception:
                    self.repo.db.rollback()
                    
            self.repo.db.commit()
            return {
                "saved_count": saved_count, 
                "skipped_count": skipped_count,
                "messages": [f"AI 분석 및 저장 완료: {saved_count}건"]
            }
        except Exception as e:
            self.repo.db.rollback()
            return {"saved_count": 0, "skipped_count": 0, "error": str(e), "messages": [f"AI 분석 중 치명적 오류: {e}"]}

    # ==========================================
    # Cluster Graph Nodes
    # ==========================================
    def node_fetch_unclustered(self, state: ClusterState) -> dict:
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
            return {"unclustered_articles": data, "messages": [f"미분류 기사 {len(data)}건 로드됨"]}
        except Exception as e:
            self.repo.db.rollback()
            return {"unclustered_articles": [], "error": str(e), "messages": [f"미분류 기사 로드 실패: {e}"]}

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

    def node_bertopic_cluster(self, state: ClusterState) -> dict:
        articles = state.get("unclustered_articles", [])
        if len(articles) < 10:
            return {"clustered_topics": [], "messages": ["분석할 기사가 너무 적어(10개 미만) 클러스터링 건너뜀"]}

        df = pd.DataFrame(articles)
        df_clean = self._remove_duplicates_fast(df)

        if len(df_clean) < 10:
            return {"clustered_topics": [], "messages": ["중복 제거 후 기사가 너무 적어 건너뜀"]}
            
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
        
        topic_model = BERTopic(
            embedding_model="snunlp/KR-SBERT-V40K-klueNLI-augSTS",
            vectorizer_model=vectorizer,
            umap_model=umap_model,
            hdbscan_model=hdbscan_model,   
            nr_topics="auto", 
            calculate_probabilities=True,
            verbose=False
        )
        
        docs = [str(t) + " " + str(t) + " " + str(t) + " " + str(c)[:100] for t, c in zip(df_clean['title'], df_clean['content'])]
        topics, _ = topic_model.fit_transform(docs)
        
        df_clean['topic_id'] = topics
        topic_info = topic_model.get_topic_info()
        top_topics = topic_info[topic_info['Topic'] != -1].head(15).copy() 

        clustered_topics = []
        for _, row in top_topics.iterrows():
            topic_id = row['Topic']
            count = row['Count']
            
            if count < 5: continue

            topic_indices = df_clean[df_clean['topic_id'] == topic_id].index
            topic_articles = df_clean.loc[topic_indices]
            
            clustered_topics.append({
                "topic_id": topic_id,
                "count": count,
                "titles": topic_articles['title'].tolist(),
                "article_ids": topic_articles['article_id'].tolist()
            })

        return {"clustered_topics": clustered_topics, "messages": [f"BERTopic 결과 {len(clustered_topics)}개 이슈 그룹 발견"]}

    def _generate_title_and_desc_with_gemini(self, titles: list):
        try:
            model = genai.GenerativeModel('gemini-2.0-flash')
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
            4. 제목은 '~명칭', '~발표', '~개최' 등 명사형으로 끝맺을 것.
            """
            response = model.generate_content(prompt)
            result_text = response.text.strip()
            if result_text.startswith("```json"):
                result_text = result_text[7:-3].strip()
            parsed = json.loads(result_text)
            
            return (
                parsed.get("title", titles[0]), 
                parsed.get("description", "이슈 요약이 제공되지 않았습니다."),
                parsed.get("background", "배경 정보 없음"),
                parsed.get("core_contentions", "주요 쟁점 정보 없음")
            )
        except Exception:
            return titles[0], "요약 생성 실패", None, None

    def node_name_and_save_issues(self, state: ClusterState) -> dict:
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
                ai_label, description, background, core_contentions = self._generate_title_and_desc_with_gemini(titles)
                
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
            return {"saved_issue_count": saved_issue_count, "messages": [f"이슈 매핑 파이프라인 종료: {saved_issue_count}개 생성 완료"]}
            
        except Exception as e:
            self.repo.db.rollback()
            return {"saved_issue_count": 0, "error": str(e), "messages": [f"저장 중 에러: {e}"]}
