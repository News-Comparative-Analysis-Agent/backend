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

    def _is_noise_cluster(self, titles: List[str], article_mode: str = "politics") -> bool:
        """비평 기사로서 가치가 떨어지는 노이즈 클러스터(단순 칼럼 묶음 등) 판별"""
        import re
        count = len(titles)
        if count < 2: return True

        # 1. 특정 패턴(브래킷 코너명)이 70% 이상 차지하는지 확인
        bracket_pattern = r'^\[(.{2,12})\]'
        matches = [re.match(bracket_pattern, t) for t in titles]
        bracket_contents = [m.group(1) for m in matches if m]
        
        # [사설], [칼럼], [단독], [포토] 등은 노이즈가 아닌 표준 분류이므로 제외
        ignore_labels = {"사설", "칼럼", "단독", "포토", "오피니언", "사설/칼럼"}
        valid_bracket_contents = [c for c in bracket_contents if c not in ignore_labels]
        
        if len(bracket_contents) / count > 0.7:
            # 유효한(무시되지 않은) 브래킷 내용들이 모두 동일한지 확인
            if not valid_bracket_contents: # 모든 브래킷이 [사설] 등인 경우 -> 노이즈 아님!
                return False
                
            prefixes = set(valid_bracket_contents)
            if len(prefixes) <= 1: # [일요진단] 처럼 특정 코너명만 반복되는 경우
                logger.info(f" 🚫 노이즈 클러스터 감지(코너명 반복): {list(prefixes)}")
                return True
        
        # 2. 사설 모드에서 제목이 너무 짧거나 정보량이 없는 경우 (추가 가능)
        return False

    def _post_merge_similar_clusters(self, clustered_topics: list, merge_threshold: float = 0.75) -> list:
        """유사한 클러스터들을 TF-IDF 코사인 유사도 기반으로 후처리 병합 (과분할 방지)"""
        if len(clustered_topics) < 2:
            return clustered_topics
        
        # 각 클러스터의 대표 텍스트 (제목들을 모두 합침)
        cluster_texts = [" ".join(t["titles"]) for t in clustered_topics]
        
        # 병합용 TF-IDF 벡터화 (ngram을 활용해 문맥 파악)
        merge_vectorizer = TfidfVectorizer(max_features=2000, ngram_range=(1, 2))
        tfidf_matrix = merge_vectorizer.fit_transform(cluster_texts)
        sim_matrix = cosine_similarity(tfidf_matrix)
        
        merged_indices = set()
        final_topics = []
        
        for i in range(len(clustered_topics)):
            if i in merged_indices:
                continue
            
            current_topic = clustered_topics[i].copy()
            
            for j in range(i + 1, len(clustered_topics)):
                if j in merged_indices:
                    continue
                
                # 유사도가 임계치를 넘으면 병합
                if sim_matrix[i][j] >= merge_threshold:
                    logger.info(f" 🔀 클러스터 병합: '{current_topic['titles'][0][:20]}...' ← '{clustered_topics[j]['titles'][0][:20]}...' (유사도: {sim_matrix[i][j]:.2f})")
                    current_topic["titles"].extend(clustered_topics[j]["titles"])
                    current_topic["article_ids"].extend(clustered_topics[j]["article_ids"])
                    current_topic["count"] += clustered_topics[j]["count"]
                    # 언론사 정보는 나중에 다시 계산하기 위해 리스트 합본 유지 (압축은 최종 단계서)
                    merged_indices.add(j)
            
            final_topics.append(current_topic)
            
        return final_topics

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
        """[고도화] TF-IDF 가중치 조정 및 후처리 병합을 포함한 정밀 클러스터링"""
        log_llm_event("ClusterAgent", "TF-IDF 정밀 클러스터링 및 후처리 노드 시작")
        articles = state.get("unclustered_articles", [])
        article_mode = state.get("article_mode", "politics")
        
        if len(articles) < 2:
            msg = f"기사 부족({len(articles)}건)으로 클러스터링을 건너뜁니다."
            return {"clustered_topics": [], "messages": [msg]}

        df = pd.DataFrame(articles)
        df_clean = self._remove_duplicates_fast(df)

        if len(df_clean) < 2:
            msg = "중복 제거 후 남은 기사가 부족합니다."
            return {"clustered_topics": [], "messages": [msg]}
            
        try:
            # 1. 문서 가중치 조정 (사설은 제목을 3배 반복)
            articles_list = df_clean.to_dict('records')
            if article_mode == "editorial":
                docs = [f"{str(art['title'])} {str(art['title'])} {str(art['title'])} {str(art['content'][:300])}" for art in articles_list]
                distance_threshold = 0.92
            else:
                docs = [f"{str(art['title'])} {str(art['content'][:500])}" for art in articles_list]
                distance_threshold = 0.8 # TODO 배포시 0.8로 변경
            
            custom_stopwords = ['기자', '특파원', '대해', '밝혔다', '관련', '오늘', '오후', '오전', '대통령', '대표', '의원', '민주당', '국민의힘', '한동훈', '이재명', '윤석열', '여야', '국회']
            vectorizer = TfidfVectorizer(max_features=5000, stop_words=custom_stopwords, ngram_range=(1, 2))
            X = vectorizer.fit_transform(docs)
            
            # 2. 계층적 군집화 수행
            from sklearn.metrics.pairwise import cosine_distances
            distance_matrix = cosine_distances(X)
            
            # [진단 코드 추가] 쌍방울 관련 기사들의 실제 거리값 확인
            keywords = ["박상용", "쌍방울", "대북송금", "녹취", "이화영"]
            target_indices = [
                i for i, art in enumerate(articles_list)
                if any(kw in art['title'] for kw in keywords)
            ]

            if len(target_indices) >= 2:
                logger.info(f"🔍 [Diagnostic] 쌍방울 관련 키워드 기사 {len(target_indices)}건 발견:")
                for i in target_indices:
                    logger.info(f"   [{i}] {articles_list[i]['title'][:40]}")
                logger.info("🔍 [Diagnostic] 상호 거리값 (Threshold: {0})".format(distance_threshold))
                for i in range(len(target_indices)):
                    for j in range(i+1, len(target_indices)):
                        idx_i, idx_j = target_indices[i], target_indices[j]
                        dist = distance_matrix[idx_i][idx_j]
                        match_symbol = "✔️ (In)" if dist <= distance_threshold else "❌ (Out)"
                        logger.info(f"   [{idx_i}] ↔ [{idx_j}] 거리: {dist:.4f} {match_symbol}")
                        logger.info(f"     ㄴ {articles_list[idx_i]['title'][:25]}...")
                        logger.info(f"     ㄴ {articles_list[idx_j]['title'][:25]}...")
            elif len(target_indices) == 1:
                logger.info(f"⚠️ [Diagnostic] 쌍방울 키워드 기사가 1건뿐입니다: {articles_list[target_indices[0]]['title']}")
            else:
                logger.info("⚠️ [Diagnostic] 쌍방울 키워드 기사를 찾지 못했습니다.")

            from sklearn.cluster import AgglomerativeClustering
            clustering_model = AgglomerativeClustering(
                n_clusters=None, 
                metric='precomputed',
                linkage='average',
                distance_threshold=distance_threshold
            )
            
            cluster_labels = clustering_model.fit_predict(distance_matrix)
            df_clean['topic_id'] = cluster_labels
            
            # 3. 1차 클러스터 조립 및 품질 필터링
            intermediate_topics = []
            for topic_id in set(cluster_labels):
                if topic_id == -1: continue
                
                topic_articles = df_clean[df_clean['topic_id'] == topic_id]
                count = len(topic_articles)
                
                # 언론사 다양성 및 집중도 체크
                media_counts = topic_articles['press'].value_counts()
                unique_press = len(media_counts)
                max_press_ratio = media_counts.iloc[0] / count if count > 0 else 1.0
                
                # 품질 조건 (사설 모드는 더 엄격하게)
                min_articles = 3
                min_press = 3 if article_mode == "editorial" else 2
                
                # 노이즈 체크 (코너명 반복 등)
                is_noise = self._is_noise_cluster(topic_articles['title'].tolist(), article_mode)
                
                if not is_noise and count >= min_articles and unique_press >= min_press and max_press_ratio <= 0.6:
                    intermediate_topics.append({
                        "topic_id": int(topic_id),
                        "count": int(count),
                        "press_count": int(unique_press),
                        "titles": topic_articles['title'].tolist(),
                        "article_ids": topic_articles['article_id'].tolist(),
                        "presses": topic_articles['press'].tolist() # 병합 후 재계산용
                    })

            # 4. 유사 클러스터 후처리 병합
            clustered_topics = self._post_merge_similar_clusters(intermediate_topics, merge_threshold=0.75)
            
            # 5. 최종 통계 업데이트
            for t in clustered_topics:
                t["press_count"] = len(set(t["presses"]))
                del t["presses"] # 불필요한 메모리 방지

            msg = f"{len(clustered_topics)}개의 고품질 이슈 군집 도출 완료 (병합 및 노이즈 제거 반영)"
            logger.info(f"[ClusterAgent:Cluster] {msg}")
            return {"clustered_topics": clustered_topics, "messages": [msg]}
        except Exception as e:
            logger.error(f"[ClusterAgent:Cluster] 치명적 오류: {e}")
            import traceback
            traceback.print_exc()
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
            
            # [안전장치] 테스트 기간 동안 노이즈 기사 자동 삭제 일시 중단
            # outlier_ids = [a.id for a in outliers]
            # from app.domains.articles.models import ArticleBody, Article
            
            # # 본문 먼저 삭제
            # self.db.query(ArticleBody).filter(ArticleBody.article_id.in_(outlier_ids)).delete(synchronize_session=False)
            # # 기사 삭제
            # deleted_count = self.db.query(Article).filter(Article.id.in_(outlier_ids)).delete(synchronize_session=False)
            
            # self.db.commit()
            msg = "정리할 노이즈 기사가 있으나, 테스트를 위해 삭제하지 않고 보존합니다."
            log_llm_event("ClusterAgent", msg)
            return {"messages": [msg]}
        except Exception as e:
            self.db.rollback()
            logger.error(f"Cleanup outliers failed: {e}")
            return {"messages": [f"노이즈 기사 정리 실패: {e}"]}
