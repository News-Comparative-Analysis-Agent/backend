# app/scroller/service.py
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random
from datetime import datetime, timedelta
import numpy as np
from bertopic import BERTopic
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from hdbscan import HDBSCAN
from umap import UMAP
import google.generativeai as genai
import json
from collections import Counter
from konlpy.tag import Okt
import os
import html
import re
from newspaper import Article as NArticle

from sqlalchemy.orm import Session
from app.scroller.repository import ScrollerRepository
from app.scroller.schemas import CrawlResponse, ClusterResponse, ResetResponse

TARGET_PRESS_DICT = {
    "한겨레": "028", "경향신문": "032", 
    "조선일보": "023", "동아일보": "020", "연합뉴스": "001"
}
DAYS_TO_CRAWL = 4

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

class ScrollerService:
    def __init__(self, db: Session):
        self.repo = ScrollerRepository(db)

    # ==========================================
    # 크롤링 비즈니스 로직
    # ==========================================
    def _get_article_detail_with_section(self, url: str):
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            res = requests.get(url, headers=headers, timeout=5)
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

            return {
                "section": section,
                "content": content,
                "image_url": image_url,
                "pub_date": pub_date
            }
        except Exception:
            return None

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
                "bias_score": 성향 강도 점수 (0.0에서 10.0 사이의 실수. 완벽한 중도는 0.0, 성향이 극단적일수록 10.0에 가깝게 부여),
            }}
            """
            response = model.generate_content(prompt)
            result_text = response.text.strip()
            if result_text.startswith("```json"):
                result_text = result_text[7:-3].strip()
            return json.loads(result_text)
        except Exception as e:
            print(f"⚠️ 기사 AI 분석 실패 ({title[:15]}...): {e}")
            return {
                "summary": "AI 요약 실패",
                "bias": "neutral",
                "bias_score": 0.0,
            }

    def execute_news_crawling(self) -> CrawlResponse:
        print("🚀 정치 뉴스 크롤링 서비스 진입...")
        
        # 1. 오래된 데이터 정리
        deleted_count = self._cleanup_old_data()
        
        # 2. 뉴스 데이터 수집 (크롤링)
        all_news = self._collect_news_from_naver()
        
        # 3. 데이터 분석 및 DB 저장
        saved_count, skipped_count = self._save_and_analyze_news(all_news)

        print(f"✅ 수집 완료: 저장 {saved_count}건, 스킵 {skipped_count}건")
        return CrawlResponse(
            status="success",
            message=f"오래된 기사 {deleted_count}개 삭제 완료. 신규 수집 진행.",
            saved_count=saved_count,
            skipped_count=skipped_count
        )

    def _cleanup_old_data(self) -> int:
        """4일 지난 과거 데이터를 삭제합니다."""
        deleted_count = self.repo.delete_old_articles(days=DAYS_TO_CRAWL)
        print(f"🧹 과거 데이터 삭제 완료: {deleted_count}건")
        return deleted_count

    def _collect_news_from_naver(self) -> list:
        """네이버 뉴스에서 정치 섹션 기사들을 수집합니다."""
        all_news = []
        seen_articles = set()
        today = datetime.now()
        headers = {"User-Agent": "Mozilla/5.0"}
        
        for day_offset in range(DAYS_TO_CRAWL):
            target_date = today - timedelta(days=day_offset)
            date_str = target_date.strftime("%Y%m%d")
            
            for press_name, oid in TARGET_PRESS_DICT.items():
                url = f"https://news.naver.com/main/ranking/office.naver?officeId={oid}&date={date_str}"
                try:
                    res = requests.get(url, headers=headers)
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
                            all_news.append({
                                "press": press_name,
                                "title": title,
                                "content": detail['content'],
                                "image_url": detail['image_url'],
                                "pub_date": detail['pub_date'],
                                "link": link
                            })
                            collected_count += 1
                        time.sleep(random.uniform(0.05, 0.1))
                except Exception:
                    pass
        return all_news

    def _save_and_analyze_news(self, news_list: list) -> tuple[int, int]:
        """수집된 기사를 AI 분석하고 DB에 저장합니다."""
        df_unique = pd.DataFrame(news_list)
        saved_count = 0
        skipped_count = 0
        
        if df_unique.empty:
            return saved_count, skipped_count

        for _, row in df_unique.iterrows():
            try:
                publisher = self.repo.get_or_create_publisher(row['press'])
                
                if self.repo.is_article_exists(row['link']):
                    skipped_count += 1
                    continue
                
                try:
                    pub_dt = pd.to_datetime(row['pub_date'])
                except:
                    pub_dt = datetime.now()
                    
                # AI를 통한 기사 속성(요약, 편향성, 점수, 논점) 추출
                time.sleep(1.0) # Rate limit 방지 방어 코드 
                print(f"   ㄴ AI 분석 중: {row['title'][:20]}...")
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
                )
                saved_count += 1
            except Exception:
                self.repo.db.rollback()
                
        self.repo.db.commit()
        return saved_count, skipped_count

    # ==========================================
    # 클러스터링 비즈니스 로직
    # ==========================================
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

    def _simple_tokenizer(self, text: str) -> list:
        okt = Okt()
        stopwords = [
            '뉴스', '종합', '속보', '기자', '특파원', '위해', '밝혔다', '대해', '관련', 
            '오늘', '오후', '오전', '것으로', '따르면', '있는', '했다', '말했다',
            '민주당', '국민의힘', '의원', '대통령', '대표', '무단전재', '배포', '금지',
            '이날', '어제', '내일', '이번', '지난', '가장', '통해', '때문', '경우', 
            '정도', '사실', '내용', '모두', '우리', '자신', '문제', '생각', '사람',
            '그', '이', '저', '수', '것', '등', '안', '전', '후', '약', '중'
        ]
        nouns = okt.nouns(str(text))
        return [n for n in nouns if n not in stopwords and len(n) >= 2]

    def _generate_title_and_desc_with_gemini(self, titles: list):
        try:
            model = genai.GenerativeModel('gemini-2.0-flash')
            prompt = f"""
            다음은 동일한 뉴스 사건에 대한 기사 제목들입니다:
            {titles[:10]} (총 {len(titles)}건)

            이 뉴스들을 분석하여 **구체적인 단일 이슈**에 대한 제목과 요약을 작성해주세요.
            
            [작성 규칙]
            1. 반드시 아래와 같은 JSON 형식으로만 응답할 것 (백틱이나 markdown 서식 없이 순수 JSON 텍스트만 출력).
            {{
                "title": "15자 이내의 구체적인 이슈 제목",
                "description": "이슈의 배경과 핵심 내용을 포함한 3~4문장의 요약"
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
            return parsed.get("title", titles[0]), parsed.get("description", "이슈 요약이 제공되지 않았습니다.")
        except Exception:
            return titles[0], "요약 생성 실패"

    def execute_clustering(self) -> ClusterResponse:
        print("🤖 클러스터링 기반 이슈 분석 서비스 진입...")
        unclustered_articles = self.repo.get_unclustered_articles()
        
        if not unclustered_articles:
            print("✨ 새로 분석할 기사가 없습니다.")
            return ClusterResponse(status="success", message="새로 분석할 기사가 없습니다.", saved_issue_count=0)

        # 1. 클러스터링 데이터 준비
        df_clean = self._prepare_clustering_data(unclustered_articles)
        
        if len(df_clean) < 10:
            print("🚫 분석할 기사가 너무 적어 건너뜁니다.")
            return ClusterResponse(status="success", message="분석할 기사가 너무 적어 건너뜁니다.", saved_issue_count=0)
            
        # 2. 토픽 모델링 수행
        topic_model, df_with_topics = self._perform_topic_modeling(df_clean)
        
        # 3. 클러스터 분석 결과 저장
        try:
            saved_issue_count = self._save_clusters_to_db(topic_model, df_with_topics)
            self.repo.db.commit()
            print(f"🎉 클러스터링 및 DB 저장 완료! 총 {saved_issue_count}개의 이슈 할당")
            return ClusterResponse(
                status="success", message="클러스터링 및 생성 완료", saved_issue_count=saved_issue_count)

            
        except Exception as e:
            self.repo.db.rollback()
            return ClusterResponse(status="error", message=str(e), saved_issue_count=0)

    def _prepare_clustering_data(self, articles: list) -> pd.DataFrame:
        """수집된 기사 리스트를 DataFrame으로 변환하고 중복을 제거합니다."""
        data = []
        for a in articles:
            content = a.body.raw_content if hasattr(a, 'body') and a.body else ""
            data.append({
                'article_id': a.id,
                'title': a.title,
                'content': content,
                'pub_date': a.published_at,
                'link': a.url
            })
            
        df = pd.DataFrame(data)
        return self._remove_duplicates_fast(df)

    def _perform_topic_modeling(self, df: pd.DataFrame) -> tuple[BERTopic, pd.DataFrame]:
        """BERTopic 모델을 학습하고 기사별 토픽 ID를 부여합니다."""
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
        
        print("🤖 BERTopic 초고해상도 학습 시작")
        topic_model = BERTopic(
            embedding_model="snunlp/KR-SBERT-V40K-klueNLI-augSTS",
            vectorizer_model=vectorizer,
            umap_model=umap_model,
            hdbscan_model=hdbscan_model,   
            nr_topics="auto", 
            calculate_probabilities=True,
            verbose=False
        )
        
        docs = [str(t) + " " + str(t) + " " + str(t) + " " + str(c)[:100] for t, c in zip(df['title'], df['content'])]
        topics, probs = topic_model.fit_transform(docs)
        
        df['topic_id'] = topics
        return topic_model, df

    def _save_clusters_to_db(self, topic_model: BERTopic, df: pd.DataFrame) -> int:
        """추출된 토픽 정보를 분석하여 DB에 저장합니다."""
        topic_info = topic_model.get_topic_info()
        top_topics = topic_info[topic_info['Topic'] != -1].head(15).copy() 
        
        saved_issue_count = 0
        for idx, row in top_topics.iterrows():
            topic_id = row['Topic']
            count = row['Count']
            
            if count < 5: continue

            topic_indices = df[df['topic_id'] == topic_id].index
            topic_articles = df.loc[topic_indices]
            topic_titles = topic_articles['title'].tolist()
            
            time.sleep(1.0) 
            ai_label, description = self._generate_title_and_desc_with_gemini(topic_titles)
            
            article_ids_to_update = topic_articles['article_id'].tolist()
            self.repo.save_issue_and_relations(
                ai_label=ai_label,
                description=description,
                count=count,
                article_ids_to_update=article_ids_to_update
            )
            print(f"   [{idx+1}위] {ai_label} (기사 {count}건 저장완료)")
            saved_issue_count += 1
            
        return saved_issue_count

    # ==========================================
    # 초기화 비즈니스 로직
    # ==========================================
    def execute_truncate(self) -> ResetResponse:
        try:
            self.repo.truncate_all_data()
            self.repo.db.commit()
            return ResetResponse(status="success", message="모든 데이터가 삭제되고 PK 1번으로 리셋되었습니다.")
        except Exception as e:
            self.repo.db.rollback()
            return ResetResponse(status="error", message=f"삭제 오류: {e}")

# ==========================================
# NLP 검색 로직 (기존 nlp_search.py 대체)
# ==========================================
class NLPSearchService:
    def __init__(self, db: Session):
        self.repo = ScrollerRepository(db)

    def generate_briefing(self, query, articles_data):
        try:
            model = genai.GenerativeModel('gemini-2.0-flash')
            context_text = ""
            for i, art in enumerate(articles_data):
                content = art.get('full_text', art['description']) 
                context_text += f"[{i+1}] 언론사: {art['source']} | 제목: {art['title']}\n내용: {content[:1000]}\n\n"

            prompt = f"""
            당신은 정치/사회 이슈 전문 분석가입니다.
            사용자가 요청한 검색어: "{query}"
            
            아래 제공된 {len(articles_data)}개의 뉴스 기사들을 종합적으로 분석하여 '이슈 브리핑 보고서'를 작성해주세요.
            
            [분석 지침]
            1. 특정 언론사의 시각에 치우치지 말고, 중립적인 입장에서 서술하십시오.
            2. 논란이 있는 이슈라면 '찬성/반대' 또는 '여당/야당/정부'의 입장을 구분하여 정리하십시오.
            3. 가장 중요한 핵심 흐름을 3문단 이내로 요약하십시오.

            [입력 데이터]
            {context_text}

            [출력 형식 (JSON)]
            {{
                "summary_content": "종합적인 요약 내용 (마크다운 형식 가능, 줄바꿈은 \\n)",
                "keywords": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"]
            }}
            """
            response = model.generate_content(prompt)
            clean_text = response.text.strip().replace("```json", "").replace("```", "")
            return json.loads(clean_text)
        except Exception as e:
            print(f"⚠️ 브리핑 생성 실패: {e}")
            return None

    def execute_search_briefing(self, user_query):
        print(f"🔍 '{user_query}' 관련 기사 우리 DB에서 검색 중...")
        items = self.repo.search_articles_by_keyword(user_query, limit=15)
        if not items: 
            return {"success": False, "message": "내부 DB에 해당 키워드를 포함한 기사가 없습니다."}

        processed_articles = []
        source_counter = Counter()

        for idx, item in enumerate(items):
            press_name = item.publisher.name if getattr(item, 'publisher', None) else "알 수 없음"
            content = item.body.raw_content if getattr(item, 'body', None) else ""
            
            art_data = {
                "title": item.title,
                "link": item.url,
                "description": content[:150] + "...",
                "pubDate": item.published_at.strftime("%Y-%m-%d %H:%M:%S") if item.published_at else "",
                "source": press_name
            }
            if idx < 3:
                # 상위 3개는 본문을 제공
                if content:
                    art_data['full_text'] = content
            processed_articles.append(art_data)
            source_counter[press_name] += 1

        print("🤖 AI 분석가가 보고서를 작성 중입니다...")
        briefing = self.generate_briefing(user_query, processed_articles)
        if not briefing:
             return {"success": False, "message": "AI 브리핑 생성에 실패했습니다."}

        final_keywords = briefing.get('keywords', [])
        formatted_articles = []
        
        for idx, art in enumerate(processed_articles):
            matched = [k for k in final_keywords if k in art['title'] or k in art['description']]
            formatted_articles.append({
                "id": f"news_{idx+1:03d}",
                "title": art['title'],
                "source": art['source'],
                "description": art['description'],
                "link": art['link'],
                "pubDate": art['pubDate'],
                "relevance_score": 0.0,
                "matching_keywords": matched
            })

        return {
            "success": True,
            "data": {
                "original_query": user_query,
                "generated_keywords": final_keywords,
                "ai_summary": briefing.get('summary_content', ''),
                "total_results": len(formatted_articles),
                "articles": formatted_articles,
                "by_source": dict(source_counter)
            }
        }
