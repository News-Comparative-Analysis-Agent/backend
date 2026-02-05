import pandas as pd
import os
from dotenv import load_dotenv
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
# ==========================================
# [설정] API 키 및 환경 설정
# ==========================================
# Load .env from backend root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(BASE_DIR, ".env"))

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") # .env 파일에서 로드
genai.configure(api_key=GOOGLE_API_KEY)

# ==========================================
# 1. 유틸리티 함수 (중복제거, 토크나이저)
# ==========================================
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
    
    # 2. 명사 추출 (nouns 함수 사용)
    nouns = okt.nouns(str(text))
    
    # 3. 불용어 제거 및 2글자 이상만 선택
    # (단, '당'(Party), '법'(Law) 처럼 1글자여도 중요한 건 살려야 함 -> 일단은 2글자 이상으로 필터링)
    filtered_nouns = [n for n in nouns if n not in stopwords and len(n) >= 2]
    
    return filtered_nouns

# ==========================================
# 2. [NEW] 키워드 네트워크 분석 함수
# ==========================================
def extract_issue_network(texts, top_n_nodes=20, top_n_edges=30):
    """
    특정 이슈에 속한 기사 텍스트들을 받아 '키워드 네트워크 JSON'을 생성합니다.
    """
    edges = []
    node_counter = Counter()

    for text in texts:
        # 기사 하나에서 단어 추출 (중복 제거하여 관계 생성)
        tokens = list(set(simple_tokenizer(text)))
        node_counter.update(tokens)
        
        # 동시 출현(Co-occurrence) 관계 형성
        for pair in combinations(tokens, 2):
            edges.append(tuple(sorted(pair)))

    # 상위 N개 키워드 추출
    top_nodes = [node for node, count in node_counter.most_common(top_n_nodes)]
    
    # 상위 M개 연결 관계 추출
    edge_counts = Counter(edges).most_common(top_n_edges)
    
    # JSON 구조 생성 (DB의 'graph_data' 컬럼에 들어갈 데이터)
    network_data = {
        "nodes": [{"id": node, "count": node_counter[node]} for node in top_nodes],
        "links": [{"source": u, "target": v, "weight": w} 
                  for (u, v), w in edge_counts 
                  if u in top_nodes and v in top_nodes]
    }
    
    # 키워드 리스트 (문자열 배열 형태)
    keyword_list = top_nodes[:10]
    
    return json.dumps(network_data, ensure_ascii=False), keyword_list

# ==========================================
# 3. Gemini 제목 생성
# ==========================================
def generate_title_with_gemini(titles):
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
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

# ==========================================
# 4. 메인 분석 로직
# ==========================================
def analyze_weekly_top10(csv_path):
    print("📥 데이터 로딩 중...")
    df = pd.read_csv(csv_path)
    
    # 1. 중복 제거
    df_clean = remove_duplicates_fast(df)
    
    print("🚀 BERTopic 학습 시작 (Full Analysis Mode)...")
    
    # 불용어 설정
    korean_stopwords = [
        "뉴스", "종합", "속보", "기자", "특파원", "위해", "밝혔다", "대해", "관련", 
        "오늘", "오후", "오전", "것으로", "따르면", "있는", "했다", "말했다",
        "민주당", "국민의힘", "의원", "대통령", "대표"
    ]
    vectorizer = CountVectorizer(stop_words=korean_stopwords)
    
    # 군집화 모델 설정
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
    
    # 제목 가중치 강화
    docs = [str(t) + " " + str(t) + " " + str(t) + " " + str(c)[:100] 
            for t, c in zip(df_clean['title'], df_clean['content'])]
            
    topics, probs = topic_model.fit_transform(docs)
    
    df_clean['topic_id'] = topics
    if probs is not None and len(probs.shape) > 1:
        df_clean['prob'] = np.max(probs, axis=1)
    else:
        df_clean['prob'] = 1.0

    print("\n🤖 이슈 분석 및 키워드 추출 중...")
    
    topic_info = topic_model.get_topic_info()
    top_topics = topic_info[topic_info['Topic'] != -1].head(15)
    
    final_results = []
    
    print(f"\n🏆 최종 이슈 리스트 (제목 + 키워드 + 그래프):")
    
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
        
        # 2) [NEW] 키워드 네트워크 데이터 생성 (JSON)
        # 제목과 본문을 합쳐서 분석 텍스트 준비
        analysis_texts = (topic_articles['title'] + " " + topic_articles['content'].fillna('')).tolist()
        graph_json, keyword_list = extract_issue_network(analysis_texts)
            
        print(f"   [{idx+1}위] {ai_label} (기사 {count}건)")
        print(f"       ㄴ 핵심 키워드: {', '.join(keyword_list[:5])}...")
        
        # 대표 기사 추출 (상위 10개만)
        representative_docs = topic_articles.sort_values(by='prob', ascending=False).head(10)
        
        for rank, (_, article) in enumerate(representative_docs.iterrows(), 1):
            final_results.append({
                "issue_rank": idx + 1,
                "issue_label": ai_label,       # AI 제목
                "keywords": ",".join(keyword_list), # 키워드 (콤마로 구분된 문자열)
                "graph_data": graph_json,      # 지식 그래프용 JSON 데이터
                "total_count": count,
                "article_rank": rank,
                "title": article['title'],
                "press": article['press'],
                "pub_date": article['pub_date'],
                "link": article['link'],
                "image_url": article.get('image_url', '') # 이미지 URL 있으면 저장
            })

    if final_results:
        result_df = pd.DataFrame(final_results)
        # CSV 파일명 설정
        filename = "weekly_top_issues_complete.csv"
        result_df.to_csv(filename, index=False, encoding="utf-8-sig")
        print(f"\n🎉 저장 완료! '{filename}' 파일을 확인하세요.")
        
        # JSON 데이터 샘플 출력 (디버깅용)
        print("\n[Sample Graph JSON Data - 1위 이슈]")
        print(result_df.iloc[0]['graph_data'][:200] + "...") 
    else:
        print("⚠️ 추출된 이슈가 없습니다.")

if __name__ == "__main__":
    analyze_weekly_top10("weekly_politics_news_clean.csv")