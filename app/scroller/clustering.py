import pandas as pd
import numpy as np
from bertopic import BERTopic
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from hdbscan import HDBSCAN
from umap import UMAP
import google.generativeai as genai
import time

GOOGLE_API_KEY = "models/gemini-2.0-flash-exp"

genai.configure(api_key=GOOGLE_API_KEY)

def remove_duplicates_fast(df, threshold=0.90):
    if df.empty: return df
    df = df.reset_index(drop=True)
    
    print(f"   🧹 중복 제거 전: {len(df)}개")
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
    print(f"중복 제거 완료: {len(df_clean)}개")
    return df_clean


def generate_title_with_gemini(titles):
    """
    기사 제목 리스트를 받아 Gemini가 '깔끔한 이슈 제목' 하나를 작명해줍니다.
    """
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        
        # 프롬프트 엔지니어링 (핵심!)
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
        print(f"   Gemini 호출 실패 (기본 제목 사용): {e}")
        
        return titles[0]


def analyze_weekly_top10(csv_path):
    df = pd.read_csv(csv_path)
    
    # 1. 중복 제거
    df_clean = remove_duplicates_fast(df)
    
    print("BERTopic 학습 시작 (Gemini 작명 모드)...")
    
    korean_stopwords = [
        "뉴스", "종합", "속보", "기자", "특파원", "위해", "밝혔다", "대해", "관련", 
        "오늘", "오후", "오전", "것으로", "따르면", "있는", "했다", "말했다",
        "민주당", "국민의힘", "의원", "대통령", "대표"
    ]
    vectorizer = CountVectorizer(stop_words=korean_stopwords)
    
    # 군집화 설정 (세밀하게)
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
    
    # 제목 가중치 3배
    docs = [str(t) + " " + str(t) + " " + str(t) + " " + str(c)[:100] 
            for t, c in zip(df_clean['title'], df_clean['content'])]
            
    topics, probs = topic_model.fit_transform(docs)
    
    df_clean['topic_id'] = topics
    if probs is not None and len(probs.shape) > 1:
        df_clean['prob'] = np.max(probs, axis=1)
    else:
        df_clean['prob'] = 1.0

    
    print("\n Gemini가 이슈 제목을 짓고 있습니다... (잠시만 기다려주세요)")
    
    topic_info = topic_model.get_topic_info()
    top_topics = topic_info[topic_info['Topic'] != -1].head(15)
    
    final_results = []
    
    print(f"\n🏆 최종 이슈 리스트 (AI 작명):")
    
    for idx, row in top_topics.iterrows():
        topic_id = row['Topic']
        count = row['Count']
        
        if count < 7: continue

        topic_indices = df_clean[df_clean['topic_id'] == topic_id].index
        topic_titles = df_clean.loc[topic_indices, 'title'].tolist()
        
        
        time.sleep(1.0) 
        ai_label = generate_title_with_gemini(topic_titles)
            
        print(f"   [{idx+1}위] {ai_label} (기사 {count}건)")
        
        representative_docs = df_clean[df_clean['topic_id'] == topic_id].sort_values(
            by='prob', ascending=False
        ).head(10)
        
        for rank, (_, article) in enumerate(representative_docs.iterrows(), 1):
            final_results.append({
                "issue_rank": idx + 1,
                "issue_label": ai_label, # AI가 지은 예쁜 제목
                "total_count": count,
                "article_rank": rank,
                "title": article['title'],
                "press": article['press'],
                "pub_date": article['pub_date'],
                "link": article['link']
            })

    if final_results:
        result_df = pd.DataFrame(final_results)
        filename = "weekly_top_issues_ai.csv"
        result_df.to_csv(filename, index=False, encoding="utf-8-sig")
        print(f"\n🎉 저장 완료! '{filename}' 파일을 확인하세요.")
    else:
        print("추출된 이슈가 없습니다.")

if __name__ == "__main__":
    analyze_weekly_top10("weekly_politics_news_clean.csv")