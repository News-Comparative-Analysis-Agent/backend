import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

import pandas as pd
import numpy as np
from bertopic import BERTopic
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from hdbscan import HDBSCAN
from umap import UMAP
import google.generativeai as genai
import time
import re
import json
from itertools import combinations
from collections import Counter
from konlpy.tag import Okt
from datetime import datetime
from app.core.database import SessionLocal, Base, engine
from app.domains.issues.models import IssueLabel
from app.domains.articles.models import Article, ArticleBody
from app.domains.topics.models import Topic
from app.domains.publishers.models import Publisher
from app.domains.keywordrelation.models import KeywordRelation

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") # .env 파일에서 로드
genai.configure(api_key=GOOGLE_API_KEY)


def remove_duplicates_fast(df, threshold=0.90):
    if df.empty: return df
    df = df.reset_index(drop=True)
    
    print(f"🧹 중복 제거 전: {len(df)}개")
    tfidf = TfidfVectorizer(max_features=1000).fit_transform(
        df['content'].str[:300].fillna('')
    )
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
            
    df_clean = df.drop(index=list(duplicates)).reset_index(drop=True)
    print(f"✨ 중복 제거 완료: {len(df_clean)}개")
    return df_clean

def simple_tokenizer(text):
    """ 
    Okt 형태소 분석기를 사용하여 '명사'만 추출합니다. 
    '단식을' -> '단식', '대표는' -> '대표' 로 깔끔하게 변환됩니다.
    """
    okt = Okt()
    
    # 1. 불용어 리스트 (계속 추가해서 관리하면 좋습니다)
    stopwords = [
        '뉴스', '종합', '속보', '기자', '특파원', '위해', '밝혔다', '대해', '관련', 
        '오늘', '오후', '오전', '것으로', '따르면', '있는', '했다', '말했다',
        '민주당', '국민의힘', '의원', '대통령', '대표', '무단전재', '배포', '금지',
        '이날', '어제', '내일', '이번', '지난', '가장', '통해', '때문', '경우', 
        '정도', '사실', '내용', '모두', '우리', '자신', '문제', '생각', '사람',
        '그', '이', '저', '수', '것', '등', '안', '전', '후', '약', '중'
    ]
    
    nouns = okt.nouns(str(text))
    filtered_nouns = [n for n in nouns if n not in stopwords and len(n) >= 2]
    
    return filtered_nouns


def extract_issue_network(texts, top_n_nodes=20, top_n_edges=30):
    """
    특정 이슈에 속한 기사 텍스트들을 받아 '키워드 네트워크 JSON'을 생성합니다.
    """
    edges = []
    node_counter = Counter()

    for text in texts:
        
        tokens = list(set(simple_tokenizer(text)))
        node_counter.update(tokens)
        
        for pair in combinations(tokens, 2):
            edges.append(tuple(sorted(pair)))

    top_nodes = [node for node, count in node_counter.most_common(top_n_nodes)]
    
    edge_counts = Counter(edges).most_common(top_n_edges)
    
    network_data = {
        "nodes": [{"id": node, "count": node_counter[node]} for node in top_nodes],
        "links": [{"source": u, "target": v, "weight": w} 
                  for (u, v), w in edge_counts 
                  if u in top_nodes and v in top_nodes]
    }
    
    keyword_list = top_nodes[:10]
    
    return json.dumps(network_data, ensure_ascii=False), keyword_list, edge_counts

def generate_title_with_gemini(titles):
    try:
        model = genai.GenerativeModel('gemini-2.0-flash')
        prompt = f"""
        다음은 동일한 뉴스 사건에 대한 기사 제목들입니다:
        {titles[:10]} (총 {len(titles)}건)

        이 뉴스들을 모두 포괄하는 **하나의 간결하고 중립적인 이슈 제목**을 작성해주세요.
        
        [작성 규칙]
        1. 15자 이내로 짧게 작성할 것.
        2. 주관적이거나 자극적인 표현을 배제할 것 (중립적 어조).
        3. '~논란', '~발표', '~개최' 등 명사형으로 끝맺을 것.
        4. 따옴표나 설명 없이 오직 제목 텍스트만 출력할 것.
        """
        response = model.generate_content(prompt)
        return response.text.strip().replace('"', '').replace("'", "")
    except Exception as e:
        print(f"   ⚠️ Gemini 호출 실패: {e}")
        return titles[0]

def save_to_db(df_articles, top_topics, keyword_data_map):
    """
    분석된 이슈, 기사, 키워드 관계를 DB에 저장합니다.
    keyword_data_map: topic_id -> (graph_json, keyword_list, edge_counts) 매핑
    """
    print("\n💾 데이터베이스 저장 시작...")
    
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    saved_issue_count = 0
    
    try:
        
        topic_name = "정치"
        topic = db.query(Topic).filter(Topic.topic == topic_name).first()
        if not topic:
            topic = Topic(topic=topic_name)
            db.add(topic)
            db.flush()
        
        for idx, row in top_topics.iterrows():
            topic_id = row['Topic']
            count = row['Count']
            
            if count < 7: continue
            
            ai_label = row.get('ai_label', f"이슈_{idx+1}")
            graph_json, keyword_list, edge_counts = keyword_data_map.get(topic_id, ({}, [], []))
            
            issue = IssueLabel(
                name=ai_label,
                keyword=keyword_list,
                total_count=int(count),
                created_at=datetime.now()
            )
            db.add(issue)
            db.flush() 
            
            today = datetime.now().date()
            for (u, v), w in edge_counts:
                if u in keyword_list and v in keyword_list:
                    rel = KeywordRelation(
                        date=today,
                        issue_label_id=issue.id,
                        keyword_a=min(u, v), 
                        keyword_b=max(u, v),
                        frequency=w
                    )
                    db.add(rel)

            topic_indices = df_articles[df_articles['topic_id'] == topic_id].index
            topic_articles = df_articles.loc[topic_indices]
            topic_articles = topic_articles.sort_values(by='prob', ascending=False)
            
            for rank, (_, row_art) in enumerate(topic_articles.iterrows(), 1):
                press_name = row_art['press']
                publisher = db.query(Publisher).filter(Publisher.name == press_name).first()
                if not publisher:
                    publisher = Publisher(name=press_name, code=press_name) # code가 없으면 name 사용
                    db.add(publisher)
                    db.flush()
                
                # 2. 기사(Article) 중복 확인 (URL 기준)
                existing_article = db.query(Article).filter(Article.url == row_art['link']).first()
                if existing_article:
                    continue # 이미 있으면 스킵
                
                article = Article(
                    topic_id=topic.id,
                    issue_label_id=issue.id,
                    publisher_id=publisher.id,
                    title=row_art['title'],
                    url=row_art['link'],
                    image_urls=[row_art['image_url']] if row_art.get('image_url') else [],
                    published_at=pd.to_datetime(row_art['pub_date']),
                    analyzed_at=datetime.now()
                )
                db.add(article)
                db.flush()
                
                # 3. 본문(ArticleBody) 저장
                # content가 너무 길면 자르거나 처리 (Postgres TEXT는 1GB까지 가능하므로 괜찮음)
                body = ArticleBody(
                    article_id=article.id,
                    raw_content=row_art['content']
                )
                db.add(body)
                
            saved_issue_count += 1
            
        db.commit()
        print(f"🎉 DB 저장 완료! 총 {saved_issue_count}개의 이슈가 저장되었습니다.")
        
    except Exception as e:
        db.rollback()
        import traceback
        print(f"⚠️ DB 저장 중 오류 발생: {e}")
        traceback.print_exc()
        print(f"   👉 문제 발생 구간 추적: issue_idx={saved_issue_count}")
    finally:
        db.close()


def analyze_weekly_top10(csv_path):
    print("데이터 로딩 중")
    df = pd.read_csv(csv_path)
    
    df_clean = remove_duplicates_fast(df)
    
    print("BERTopic 학습 시작")
    
    korean_stopwords = [
        "뉴스", "종합", "속보", "기자", "특파원", "위해", "밝혔다", "대해", "관련", 
        "오늘", "오후", "오전", "것으로", "따르면", "있는", "했다", "말했다",
        "민주당", "국민의힘", "의원", "대통령", "대표"
    ]
    vectorizer = CountVectorizer(stop_words=korean_stopwords)
    
    hdbscan_model = HDBSCAN(min_cluster_size=7, min_samples=3, prediction_data=True)
    
    topic_model = BERTopic(
        embedding_model="snunlp/KR-SBERT-V40K-klueNLI-augSTS",
        vectorizer_model=vectorizer,
        hdbscan_model=hdbscan_model,   
        nr_topics="auto",
        min_topic_size=7,
        calculate_probabilities=True,
        verbose=True
    )
    
    docs = [str(t) + " " + str(t) + " " + str(t) + " " + str(c)[:100] 
            for t, c in zip(df_clean['title'], df_clean['content'])]
            
    topics, probs = topic_model.fit_transform(docs)
    
    df_clean['topic_id'] = topics
    if probs is not None and len(probs.shape) > 1:
        df_clean['prob'] = np.max(probs, axis=1)
    else:
        df_clean['prob'] = 1.0

    print("\n이슈 분석 및 키워드 추출 중...")
    
    topic_info = topic_model.get_topic_info()
    top_topics = topic_info[topic_info['Topic'] != -1].head(15).copy() # 복사본 사용
    
    keyword_data_map = {} 
    
    print(f"\n최종 이슈 리스트 추론 중:")
    
    for idx, row in top_topics.iterrows():
        topic_id = row['Topic']
        count = row['Count']
        
        if count < 7: continue

        # 해당 이슈의 기사들 추출
        topic_indices = df_clean[df_clean['topic_id'] == topic_id].index
        topic_articles = df_clean.loc[topic_indices]
        topic_titles = topic_articles['title'].tolist()
        
        # 1) Gemini 제목 생성
        time.sleep(1.0) 
        ai_label = generate_title_with_gemini(topic_titles)
        top_topics.at[idx, 'ai_label'] = ai_label # DataFrame에 저장
        
        # 2) [NEW] 키워드 네트워크 데이터 생성 (JSON)
        # 제목과 본문을 합쳐서 분석 텍스트 준비
        analysis_texts = (topic_articles['title'] + " " + topic_articles['content'].fillna('')).tolist()
        graph_json, keyword_list, edge_counts = extract_issue_network(analysis_texts)
        
        keyword_data_map[topic_id] = (graph_json, keyword_list, edge_counts)
            
        print(f"   [{idx+1}위] {ai_label} (기사 {count}건)")
        print(f"       ㄴ 핵심 키워드: {', '.join(keyword_list[:5])}...")
        
    # DB 저장 호출
    save_to_db(df_clean, top_topics, keyword_data_map)

if __name__ == "__main__":
    analyze_weekly_top10("weekly_politics_news_clean.csv")