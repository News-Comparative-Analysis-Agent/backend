import pandas as pd
import numpy as np
import gc
import time
import json
import logging
from typing import List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from hdbscan import HDBSCAN
from umap import UMAP
from bertopic import BERTopic

from app.scroller.repository import ScrollerRepository
from app.agents.state import ComparisonState
from app.core.logger import logger, log_llm_event
from app.agents.utils import parse_llm_json, call_llm, call_llm_text, update_total_tokens
import concurrent.futures

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

        logger.info("🤖 ClusterAgent: BERTopic 모델 로딩 시작...")
        
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
        hdbscan_model = HDBSCAN(min_cluster_size=4, min_samples=2, metric='euclidean', cluster_selection_method='eom', prediction_data=True, cluster_selection_epsilon=0.05)
        
        ClusterAgent._topic_model = BERTopic(
            embedding_model="snunlp/KR-SBERT-V40K-klueNLI-augSTS",
            vectorizer_model=vectorizer,
            umap_model=umap_model,
            hdbscan_model=hdbscan_model,   
            nr_topics="auto", 
            calculate_probabilities=True,
            verbose=False
        )
        logger.info("✅ ClusterAgent: BERTopic 모델 로드 완료.")
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

    def _generate_issue_details_with_llm(self, titles: List[str], state: Dict[str, Any]) -> Tuple[str, str, str, str]:
        """이슈 그룹에 대해 제목과 배경 등을 생성"""
        try:
            prompt = f"""
            당신은 뉴스 요약 및 이슈 추출가입니다. 중요 배경 지식을 먼저 숙지하세요:
            [현재 시점: 2026년 3월]
            [현재 대한민국 대통령: 이재명 (더불어민주당 출신)]
            [과거 대통령: 윤석열, 문재인, 박근혜, 이명박 등]
            
            ※ 제목이나 본문에 '이 대통령'이라는 수식어가 등장할 경우, 문맥상 특별한 이유가 없다면 현직인 '이재명 대통령'을 지칭하는 것입니다. 이를 과거의 '이명박 대통령'으로 오해하여 요약명에 "이명박"을 적는 환각(Hallucination) 현상을 절대 일으키지 마세요.
            
            다음은 동일한 뉴스 사건에 대한 기사 제목들입니다:
            {titles[:15]} (총 {len(titles)}건)

            이 뉴스 제목들을 철저히 분석하여 구체적인 단일 이슈에 대한 제목, 요약, 발단, 주요 쟁점을 작성해주세요.
            
            [작성 규칙]
            1. 반드시 아래와 같은 JSON 형식으로만 응답할 것.
            {{
                "title": "15자 이내의 구체적인 이슈 제목",
                "description": "이슈의 배경과 핵심 내용을 포함한 3~4문장의 요약",
                "background": "이 이슈가 발생하게 된 핵심 발단 또는 배경 설명 (1~2문장)",
                "core_contentions": "이 이슈와 관련된 주요 쟁점이나 갈등 (1~2문장)"
            }}
            2. 할루시네이션 절대 금지: 제공된 제목 텍스트 안에 있는 팩트만 사용하십시오.
            3. 기사에 등장하는 실명, 사건명이 제목에 명확히 드러나야 합니다.
            4. 제목은 명사형으로 끝맺을 것.
            """
            
            # call_llm은 utils.py에 정의된 공통 함수를 사용합니다. (반환: 결과, 토큰정보)
            parsed, usage = call_llm(prompt, "7B_1", state)
            
            # 토큰 업데이트
            state["total_tokens"] = update_total_tokens(state, usage)
            
            if parsed:
                return (
                    parsed.get("title", titles[0]), 
                    parsed.get("description", "이슈 요약 부재"),
                    parsed.get("background", "배경 정보 부재"),
                    parsed.get("core_contentions", "주요 쟁점 부재")
                )
            return titles[0], "요약 생성 실패", "배경 부재", "쟁점 부재"
        except Exception as e:
            logger.error(f"Issue LLM labeling failed: {e}")
            return titles[0], "에러 발생", "배경 부재", "쟁점 부재"

    def _extract_core_event(self, article: dict, state: ComparisonState) -> Tuple[str, Dict[str, int]]:
        """단일 기사에서 핵심 사건(Entity + Action)만 20자 이내로 추출"""
        title = article.get('title', '')
        content_lead = article.get('content', '')[:150]
        
        prompt = f"""
        당신은 뉴스 데이터 분류기입니다. 중요 배경 지식을 숙지하세요:
        [현재 시점: 2026년 3월]
        [현재 대한민국 대통령: 이재명 (더불어민주당 출신)]
        [과거 대통령: 윤석열, 문재인, 박근혜, 이명박 등]
        
        기사에 '이 대통령'이라고 나오면 문맥을 고려하되 기본적으로 '이재명 대통령'을 뜻합니다. 과거의 '이명박 대통령'으로 착각하는 환각(Hallucination)을 일으키지 마세요.
        
        다음 기사의 제목과 내용을 읽고, 이 기사가 다루는 '핵심 사건'을 20자 이내의 명사구로 요약하십시오.
        (예: "의대 증원 반발 전공의 파업", "민주당 특검법 발의", "이재명 대통령 지지율 하락")
        
        [제목]: {title}
        [내용]: {content_lead}
        
        오직 요약된 핵심 사건 키워드 딱 1줄만 출력하십시오. 부연 설명 금지.
        """
        
        try:
            # call_llm_text 사용 (순수 텍스트 결과)
            core_event, usage = call_llm_text(prompt, "7B_1", state)
            core_event = core_event.strip().replace('"', '')
            if len(core_event) > 30: core_event = core_event[:30]
            return core_event or title, usage
        except Exception as e:
            logger.error(f"Core event 추출 실패: {e}")
            return title, {"prompt_tokens": 0, "completion_tokens": 0}

    # ==========================================
    # Graph Nodes
    # ==========================================
    def node_fetch_unclustered(self, state: ComparisonState) -> Dict[str, Any]:
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
            logger.info(f"📊 [ClusterAgent:Fetch] {msg}")
            return {"unclustered_articles": data, "messages": [msg]}
        except Exception as e:
            msg = f"미분류 기사 로드 실패: {e}"
            log_llm_event("ClusterAgent", msg, type="ERROR")
            return {"unclustered_articles": [], "error": str(e), "messages": [msg]}

    def node_lexical_cluster(self, state: ComparisonState) -> Dict[str, Any]:
        """[완전 개편] TF-IDF와 계층적 군집화를 이용한 사건 단위(Event-level) 날카로운 클러스터링"""
        log_llm_event("ClusterAgent", "TF-IDF 기반 날카로운 클러스터링 연산 노드 시작")
        articles = state.get("unclustered_articles", [])
        logger.info(f"📊 [ClusterAgent:Cluster] 입력 기사 수: {len(articles)}건")
        
        if len(articles) < 5:
            msg = f"기사 부족({len(articles)}건)으로 클러스터링을 건너뜁니다. (최소 5건 필요)"
            logger.warning(f"📊 [ClusterAgent:Cluster] {msg}")
            return {"clustered_topics": [], "messages": [msg]}

        df = pd.DataFrame(articles)
        df_clean = self._remove_duplicates_fast(df)

        if len(df_clean) < 3:
            msg = "중복 제거 후 남은 기사가 부족(3건 미만)하여 클러스터링을 건너뜁니다."
            logger.warning(f"📊 [ClusterAgent:Cluster] {msg}")
            return {"clustered_topics": [], "messages": [msg]}
            
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.cluster import AgglomerativeClustering
            from sklearn.metrics.pairwise import cosine_distances

            logger.info(f"🧠 [ClusterAgent] {len(df_clean)}개 기사의 핵심 사건(Core Event) LLM 추출 시작...")
            
            # 병렬로 핵심 사건 추출
            articles_list = df_clean.to_dict('records')
            core_events = []
            total_usage = {"prompt_tokens": 0, "completion_tokens": 0}
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                results = list(executor.map(lambda x: self._extract_core_event(x, state), articles_list))
                
            for event, usage in results:
                core_events.append(event)
                total_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                total_usage["completion_tokens"] += usage.get("completion_tokens", 0)
            
            state["total_tokens"] = update_total_tokens(state, total_usage)
            df_clean['core_event'] = core_events

            # TF-IDF 임베딩 (핵심 사건 + 제목)
            docs = [f"{str(event)} {str(title)}" for event, title in zip(df_clean['core_event'], df_clean['title'])]
            
            custom_stopwords = ['기자', '특파원', '대해', '밝혔다', '관련', '오늘', '오후', '오전', '대통령', '대표', '의원', '민주당', '국민의힘', '한동훈', '이재명', '윤석열', '여야', '국회']
            vectorizer = TfidfVectorizer(max_features=5000, stop_words=custom_stopwords, ngram_range=(1, 2))
            X = vectorizer.fit_transform(docs)
            
            distance_matrix = cosine_distances(X)
            
            clustering_model = AgglomerativeClustering(
                n_clusters=None, 
                metric='precomputed',
                linkage='average',
                distance_threshold=0.75
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
                
                if count >= 2 and unique_press_count >= 1:
                    clustered_topics.append({
                        "topic_id": int(topic_id),
                        "count": int(count),
                        "press_count": int(unique_press_count),
                        "titles": topic_articles['title'].tolist(),
                        "article_ids": topic_articles['article_id'].tolist()
                    })

            msg = f"{len(clustered_topics)}개의 정밀한 이슈 군집 도출 완료"
            logger.info(f"📊 [ClusterAgent:Cluster] {msg}")
            
            for i, t in enumerate(clustered_topics, 1):
                logger.info(f"   🔥 Issue {i} ({t['count']}건, {t['press_count']}개 언론사):")
                for title in t['titles'][:5]:
                    logger.info(f"      - {title}")
                    
            return {"clustered_topics": clustered_topics, "messages": [msg]}
        except Exception as e:
            logger.error(f"📊 [ClusterAgent:Cluster] 치명적 오류: {e}")
            return {"clustered_topics": [], "messages": [f"클러스터링 중단됨: {e}"]}

    def node_name_and_save_issues(self, state: ComparisonState) -> Dict[str, Any]:
        """이슈 명명 및 저장, 그리고 분석 대상 issue_id 자동 결정"""
        log_llm_event("ClusterAgent", "이슈 저장 및 다음 타겟 선정 노드 시작")
        topics = state.get("clustered_topics", [])
        if not topics:
            msg = "분류된 토픽이 없어 이슈 저장 단계를 건너뜁니다."
            logger.info(f"📊 [ClusterAgent:Save] {msg}")
            return {"issue_id": None, "messages": [msg]}

        logger.info(f"📊 [ClusterAgent:Save] 입력 토픽 수: {len(topics)}건")

        saved_ids = []
        max_count = 0
        target_issue_id = None

        try:
            for t in topics:
                time.sleep(0.5)
                ai_label, desc, bg, core = self._generate_issue_details_with_llm(t["titles"], state)
                
                issue = self.repo.save_issue_and_relations(
                    ai_label=ai_label,
                    description=desc,
                    count=t["count"],
                    article_ids_to_update=t["article_ids"],
                    background=bg,
                    core_contentions=core
                )
                saved_ids.append(issue.id)
                # 가장 기사가 많은 이슈를 다음 분석 타겟으로 선정
                if t["count"] > max_count:
                    max_count = t["count"]
                    target_issue_id = issue.id
                    target_description = desc
                    target_background = bg
            
            self.db.commit()
            msg = f"이슈 {len(saved_ids)}개 저장 완료. 다음 분석 이슈 ID: {target_issue_id}"
            logger.info(f"📊 [ClusterAgent:Save] {msg}")
            
            # 다음 분석 단계를 위해 선택된 타겟의 상세 정보를 상태에 기록
            return {
                "issue_id": target_issue_id, 
                "description": target_description if 'target_description' in locals() else None,
                "background": target_background if 'target_background' in locals() else None,
                "total_tokens": state.get("total_tokens"),
                "messages": [msg]
            }
        except Exception as e:
            self.db.rollback()
            logger.error(f"📊 [ClusterAgent:Save] 이슈 저장 실패: {e}")
            return {"error": str(e), "messages": [f"이슈 저장 실패: {e}"]}

    def node_cleanup_unclustered(self, state: ComparisonState) -> Dict[str, Any]:
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
