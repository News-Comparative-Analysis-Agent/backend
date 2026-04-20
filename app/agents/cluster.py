import pandas as pd
import numpy as np
import gc
import time
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from hdbscan import HDBSCAN
from umap import UMAP
from bertopic import BERTopic

from app.scroller.repository import ScrollerRepository

from app.core.logger import logger, log_llm_event
from app.agents.utils import parse_llm_json, call_llm, call_llm_text, update_total_tokens
import concurrent.futures
from langsmith import traceable

class ClusterAgent:
    """
    이슈 클러스터링 및 관리를 담당하는 에이전트
    BERTopic을 사용한 군집화 및 LLM을 통한 이슈 명명 기능을 제공합니다.
    """
    _topic_model = None

    def __init__(self, db: Session):
        self.db = db
        self.repo = ScrollerRepository(db)

    def _get_topic_model(self):
        """BERTopic 모델 싱글톤 반환 (지연 로딩)"""
        if ClusterAgent._topic_model is not None:
            return ClusterAgent._topic_model

        logger.info("ClusterAgent: BERTopic 모델 로딩 시작...")
        
        korean_stopwords = [
            "뉴스", "종합", "속보", "기자", "특파원", "위해", "밝혔다", "대해", "관련", 
            "오늘", "오후", "오전", "것으로", "따르면", "있는", "했다", "말했다",
            "민주당", "국민의힘", "의원", "대통령", "대표", "정부", "국회", "여야",
            "국민", "라며", "대한", "상황", "입장", "발언", "논란", "한국", "우리",
            "이재명", "윤석열", "한동훈", "장관", "수사", "주장", "평가", "문제", "이유",
            "이날", "예정", "시간", "최근", "다시", "크게", "이후", "통해", "사실", "한동훈",
            "국민의힘", "더불어민주당", "이재명", "윤석열", "조국"
        ]
        
        vectorizer = CountVectorizer(stop_words=korean_stopwords, ngram_range=(1, 2))
        umap_model = UMAP(n_neighbors=10, n_components=5, min_dist=0.0, metric='cosine', random_state=42)
        hdbscan_model = HDBSCAN(min_cluster_size=2, min_samples=2, metric='euclidean', cluster_selection_method='eom', prediction_data=True, cluster_selection_epsilon=0.05)
        
        ClusterAgent._topic_model = BERTopic(
            embedding_model="snunlp/KR-SBERT-V40K-klueNLI-augSTS",
            vectorizer_model=vectorizer,
            umap_model=umap_model,
            hdbscan_model=hdbscan_model,   
            nr_topics="auto", 
            calculate_probabilities=True,
            verbose=False
        )
        logger.info(" ClusterAgent: BERTopic 모델 로드 완료.")
        return ClusterAgent._topic_model

    def _remove_duplicates_fast(self, df: pd.DataFrame, threshold: float = 0.95) -> pd.DataFrame:
        if df.empty or len(df) < 2: return df
        tfidf = TfidfVectorizer(max_features=1000).fit_transform(df['content'].str[:300].fillna(''))
        duplicates = set()
        num_docs = len(df)
        
        # 마지막 기사는 비교할 다음 기사가 없으므로 num_docs - 1까지 수행
        for i in range(num_docs - 1):
            if i in duplicates: continue
            # i+1부터의 기사들과 비교
            similarities = cosine_similarity(tfidf[i], tfidf[i+1:])
            if similarities.size > 0:
                target_indices = np.where(similarities[0] > threshold)[0]
                # target_indices는 i+1부터 시작하므로 오프셋 조정
                duplicates.update(target_indices + (i + 1))
                
        return df.drop(index=list(duplicates)).copy()

    @traceable(name="Agent 0: Cluster (이슈 라벨링 LLM) 🏷️")
    def _generate_issue_details_with_llm(self, titles: List[str], state: Dict[str, Any]) -> Tuple[str, str, str, str, dict]:
        """이슈 그룹에 대해 제목과 배경 등을 생성. (title, desc, background, core, usage) 5-tuple 반환"""
        empty_usage = {"prompt_tokens": 0, "completion_tokens": 0}
        try:
            prompt = f"""
            당신은 뉴스 기사 제목을 분석하여 사건의 핵심 맥락을 정리하는 전문가입니다.
            아래 기사 제목들은 동일한 뉴스 사건을 다룬 여러 언론사의 제목입니다.
            제목들을 바탕으로 이 사건의 핵심 정보를 정리하십시오.

            [기사 제목 목록]
            {titles[:15]} (총 {len(titles)}건)

            [작성 규칙]
            1. title: 이 사건을 한눈에 알 수 있는 구체적인 제목을 작성하라. 제목에 나온 핵심 단어(인물명, 사건명, 의혹명 등)를 반드시 포함하라.
            2. description: 무슨 사건인지, 누가 관련되었는지, 어떤 주장이 제기되었는지를 사실 중심으로 2~3문장으로 서술하라. 언론사 간 반응이 엇갈리는 경우 그 구도를 한 문장으로 덧붙여라.
            3. background: 이 사건이 왜 발생했는지, 어떤 맥락에서 불거졌는지 배경을 1~2문장으로 서술하라. 사실에 기반하고 기사 제목에 없는 내용을 추측하지 마라.
            4. core_contentions: 이 사건을 둘러싸고 어떤 주장이 충돌하고 있는지 1문장으로 서술하라. 'A 측은 ~라고 주장하고, B 측은 ~라고 반박한다' 형식으로 작성하라.
            5. 할루시네이션 방지: 제공된 제목에 없는 사실을 추가하지 마라. 제목에 나타난 단어(예: '조작', '회유', '가짜뉴스')는 그대로 활용하라.

            [응답 예시]
            {{
                "title": "박상용 검사 '이재명 주범 자백' 발언 녹취 공개 파문",
                "description": "더불어민주당이 쌍방울 대북송금 사건을 수사한 박상용 검사가 변호인에게 '이재명이 주범이 되는 자백이 있어야 한다'고 말한 녹취를 공개해 파문이 일고 있다. 주요 언론사들은 '전체 녹취를 공개해야 한다'는 입장과 '국정조사에서 진상을 규명해야 한다'는 입장으로 엇갈렸다.",
                "background": "쌍방울 대북송금 사건 수사 과정에서 검사가 피의자 측 변호인에게 특정 진술을 유도했다는 의혹이 제기됐으며, 민주당은 이를 표적 수사의 증거로 주장하고 있다.",
                "core_contentions": "민주당은 검사의 발언이 진술 회유의 증거라고 주장하고, 검찰은 해당 녹취가 편집·왜곡됐다고 반박한다."
            }}
            """
            
            response_schema = {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "background": {"type": "string"},
                    "core_contentions": {"type": "string"}
                },
                "required": ["title", "description", "background", "core_contentions"]
            }
            
            # call_llm은 utils.py에 정의된 공통 함수를 사용합니다. (반환: 결과, 토큰정보)
            parsed, usage = call_llm(prompt=prompt, model_size="local", state=state, schema=response_schema)
            # ✅ state 직접 변이 제거 — usage만 반환하여 호출부에서 누적 처리
            
            if parsed:
                return (
                    parsed.get("title", titles[0]), 
                    parsed.get("description", "이슈 요약 부재"),
                    parsed.get("background", "배경 정보 부재"),
                    parsed.get("core_contentions", "주요 쟁점 부재"),
                    usage
                )
            return titles[0], "요약 생성 실패", "배경 부재", "쟁점 부재", empty_usage
        except Exception as e:
            logger.error(f"Issue LLM labeling failed: {e}")
            return titles[0], "에러 발생", "배경 부재", "쟁점 부재", empty_usage

    # ==========================================
    # Graph Nodes
    # ==========================================
    @traceable(name="Agent 0: Cluster (미분류 기사 로드) 📂")
    def node_fetch_unclustered(self, state: dict) -> Dict[str, Any]:
        """미분류 기사 로드"""
        log_llm_event("ClusterAgent", "미분류 기사 로드 노드 시작")
        try:
            self.db.rollback()
            unclustered = self.repo.get_unclustered_articles()
            data = []
            for a in unclustered:
                content = a.body.raw_content if hasattr(a, 'body') and a.body else ""
                data.append({
                    'article_id': a.id,
                    'title': a.title,
                    'content': content,
                    'press': a.publisher.name if a.publisher else "알수없음"
                })
            
            msg = f"미분류 기사 {len(data)}건 로드됨"
            logger.info(f"[ClusterAgent:Fetch] {msg}")
            return {"unclustered_articles": data, "messages": [msg]}
        except Exception as e:
            msg = f"미분류 기사 로드 실패: {e}"
            log_llm_event("ClusterAgent", msg, type="ERROR")
            return {"unclustered_articles": [], "error": str(e), "messages": [msg]}

    @traceable(name="Agent 0: Cluster (정밀 이슈 군집화) 🧶")
    def node_lexical_cluster(self, state: dict) -> Dict[str, Any]:
        """[완전 개편] TF-IDF와 계층적 군집화를 이용한 사건 단위(Event-level) 날카로운 클러스터링"""
        log_llm_event("ClusterAgent", "TF-IDF 기반 날카로운 클러스터링 연산 노드 시작")
        articles = state.get("unclustered_articles", [])
        logger.info(f" [ClusterAgent:Cluster] 현재 State 키 목록: {list(state.keys())}")
        logger.info(f" [ClusterAgent:Cluster] 입력 기사 수: {len(articles)}건")
        
        if len(articles) < 2:
            msg = f"기사 부족({len(articles)}건)으로 클러스터링을 건너뜁니다. (최소 2건 필요)"
            logger.warning(f"[ClusterAgent:Cluster] {msg}")
            return {"clustered_topics": [], "messages": [msg]}

        df = pd.DataFrame(articles)
        df_clean = self._remove_duplicates_fast(df)

        if len(df_clean) < 2:
            msg = "중복 제거 후 남은 기사가 부족(2건 미만)하여 클러스터링을 건너뜁니다."
            logger.warning(f"[ClusterAgent:Cluster] {msg}")
            return {"clustered_topics": [], "messages": [msg]}
            
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.cluster import AgglomerativeClustering
            from sklearn.metrics.pairwise import cosine_distances

            # docs 조립: 제목(Title) + 본문 앞부분(Content[:500]) 활용
            articles_list = df_clean.to_dict('records')
            docs = [f"{str(art['title'])} {str(art['content'][:500])}" for art in articles_list]
            
            custom_stopwords = ['기자', '특파원', '대해', '밝혔다', '관련', '오늘', '오후', '오전', '대통령', '대표', '의원', '민주당', '국민의힘', '한동훈', '이재명', '윤석열', '여야', '국회']
            vectorizer = TfidfVectorizer(max_features=5000, stop_words=custom_stopwords, ngram_range=(1, 2))
            X = vectorizer.fit_transform(docs)
            
            distance_matrix = cosine_distances(X)
            
            clustering_model = AgglomerativeClustering(
                n_clusters=None, 
                metric='precomputed',
                linkage='average',
                distance_threshold=0.88
            )
            
            cluster_labels = clustering_model.fit_predict(distance_matrix)
            df_clean['topic_id'] = cluster_labels
            
            clustered_topics = []
            unique_labels = set(cluster_labels)
            
            for topic_id in unique_labels:
                if topic_id == -1: continue
                
                topic_articles = df_clean[df_clean['topic_id'] == topic_id]
                count = len(topic_articles)
                unique_press_count = topic_articles['press'].nunique()
                
                if count >= 3 and unique_press_count >= 2:
                    clustered_topics.append({
                        "topic_id": int(topic_id),
                        "count": int(count),
                        "press_count": int(unique_press_count),
                        "titles": topic_articles['title'].tolist(),
                        "article_ids": topic_articles['article_id'].tolist()
                    })

            msg = f"{len(clustered_topics)}개의 정밀한 이슈 군집 도출 완료"
            logger.info(f"[ClusterAgent:Cluster] {msg}")
            
            for i, t in enumerate(clustered_topics, 1):
                logger.info(f"   Issue {i} ({t['count']}건, {t['press_count']}개 언론사):")
                for title in t['titles'][:5]:
                    logger.info(f"      - {title}")
                    
            return {"clustered_topics": clustered_topics, "messages": [msg]}
        except Exception as e:
            logger.error(f"[ClusterAgent:Cluster] 치명적 오류: {e}")
            return {"clustered_topics": [], "messages": [f"클러스터링 중단됨: {e}"]}

    @traceable(name="Agent 0: Cluster (이슈 생성 및 최적 이슈 선정) 💾")
    def node_name_and_save_issues(self, state: dict) -> Dict[str, Any]:
        """이슈 명명 및 저장, 그리고 분석 대상 issue_id 자동 결정"""
        log_llm_event("ClusterAgent", "이슈 저장 및 다음 타겟 선정 노드 시작")
        topics = state.get("clustered_topics", [])
        if not topics:
            msg = "분류된 토픽이 없어 이슈 저장 단계를 건너뜁니다."
            logger.info(f"[ClusterAgent:Save] {msg}")
            return {"issue_id": None, "messages": [msg]}

        logger.info(f"[ClusterAgent:Save] 입력 토픽 수: {len(topics)}건")

        saved_ids = []
        max_count = 0
        target_issue_id = None
        # 노드 내 토큰 누적용 로컬 변수 (state 직접 변이 방지)
        node_usage = {"prompt_tokens": 0, "completion_tokens": 0}

        try:
            for t in topics:
                time.sleep(0.5)
                # ✅ 5-tuple로 usage까지 받아서 로컬에서 누적
                ai_label, desc, bg, core, usage = self._generate_issue_details_with_llm(t["titles"], state)
                node_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                node_usage["completion_tokens"] += usage.get("completion_tokens", 0)
                
                issue = self.repo.save_issue_and_relations(
                    ai_label=ai_label,
                    description=desc,
                    count=t["count"],
                    article_ids_to_update=t["article_ids"],
                    background=bg,
                    core_contentions=core
                )
                saved_ids.append(issue.id)
            
            self.db.commit()
            msg = f"이슈 {len(saved_ids)}개 저장 완료 및 모든 이슈 분석 대기 중."
            logger.info(f"[ClusterAgent:Save] {msg}")
            
            # ✅ 토큰을 return dict에 포함하여 LangGraph 리듀서를 통해 정상 업데이트
            total_tokens = update_total_tokens(state, node_usage, "ClusterAgent")
            return {
                "all_issue_ids": saved_ids, 
                "saved_issue_count": len(saved_ids),
                "total_tokens": total_tokens,
                "messages": [msg]
            }
        except Exception as e:
            self.db.rollback()
            logger.error(f"[ClusterAgent:Save] 이슈 저장 실패: {e}")
            return {"error": str(e), "messages": [f"이슈 저장 실패: {e}"]}

    @traceable(name="Agent 0: Cluster (노이즈 리셋) 🧹")
    def node_cleanup_unclustered(self, state: dict) -> Dict[str, Any]:
        """이슈에 할당되지 않은(Outlier) 기사들 DB에서 삭제"""
        log_llm_event("ClusterAgent", "미분류 노이즈 기사 정리 노드 시작")
        try:
            # issue_label_id가 여전히 NULL인 기사들 조회
            outliers = self.repo.get_unclustered_articles()
            if not outliers:
                return {"messages": ["정리할 노이즈 기사 없음"]}
            
            outlier_ids = [a.id for a in outliers]
            from app.domains.articles.models import ArticleBody, Article
            
            # 본문 먼저 삭제
            self.db.query(ArticleBody).filter(ArticleBody.article_id.in_(outlier_ids)).delete(synchronize_session=False)
            # 기사 삭제
            deleted_count = self.db.query(Article).filter(Article.id.in_(outlier_ids)).delete(synchronize_session=False)
            
            self.db.commit()
            msg = f"이슈 미지정 노이즈 기사 {deleted_count}건 삭제 완료"
            log_llm_event("ClusterAgent", msg)
            return {"messages": [msg]}
        except Exception as e:
            self.db.rollback()
            logger.error(f"Cleanup outliers failed: {e}")
            return {"messages": [f"노이즈 기사 정리 실패: {e}"]}
