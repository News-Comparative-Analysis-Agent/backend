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

import threading

class ClusterAgent:
    """
    이슈 클러스터링 및 관리를 담당하는 에이전트
    BERTopic을 사용한 군집화 및 LLM을 통한 이슈 명명 기능을 제공합니다.
    """
    _topic_model = None
    _model_lock = threading.Lock()  # 싱글톤 동시 초기화 방지용 Lock

    def __init__(self, db: Session):
        self.db = db
        self.repo = ScrollerRepository(db)

    def _get_topic_model(self):
        """BERTopic 모델 싱글톤 반환 (지연 로딩, 스레드 안전)"""
        if ClusterAgent._topic_model is not None:
            return ClusterAgent._topic_model

        with ClusterAgent._model_lock:
            # Lock 획득 후 재확인 (Double-Checked Locking)
            if ClusterAgent._topic_model is not None:
                return ClusterAgent._topic_model

            logger.info("ClusterAgent: BERTopic 모델 로딩 시작...")

            korean_stopwords = [
                "뉴스", "종합", "속보", "기자", "특파원", "위해", "밝혔다", "대해", "관련",
                "오늘", "오후", "오전", "것으로", "따르면", "있는", "했다", "말했다",
                "민주당", "국민의힘", "의원", "대통령", "대표", "정부", "국회", "여야",
                "국민", "라며", "대한", "상황", "입장", "발언", "논란", "한국", "우리",
                "이재명", "윤석열", "한동훈", "장관", "수사", "주장", "평가", "문제", "이유",
                "이날", "예정", "시간", "최근", "다시", "크게", "이후", "통해", "사실",
                "더불어민주당", "조국"
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
            logger.info("ClusterAgent: BERTopic 모델 로드 완료.")
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
                    current_topic["snippets"].extend(clustered_topics[j]["snippets"])
                    current_topic["article_ids"].extend(clustered_topics[j]["article_ids"])
                    current_topic["count"] += clustered_topics[j]["count"]
                    current_topic["presses"].extend(clustered_topics[j]["presses"])
                    current_topic["snippet_presses"].extend(clustered_topics[j].get("snippet_presses", []))
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

    def _extract_snippet(self, content: str, total_chars: int = 600) -> str:
        """앞/중/뒤 균등 샘플링으로 기사 전체 맥락 확보"""
        if not content:
            return ""
        length = len(content)
        if length <= total_chars:
            return content
        chunk = total_chars // 3
        front  = content[:chunk]
        middle = content[length//2 - chunk//2 : length//2 + chunk//2]
        end    = content[length - chunk:]
        return f"{front} [...] {middle} [...] {end}"

    @traceable(name="Agent 0: Cluster (이슈 라벨링 LLM) 🏷️")
    def _generate_issue_details_with_llm(self, titles: List[str], snippets: List[str], state: Dict[str, Any], snippet_presses: List[str] = None) -> Tuple[str, str, str, dict]:
        """이슈 그룹에 대해 제목과 배경 등을 생성. (title, desc, background, usage) 4-tuple 반환"""
        empty_usage = {"prompt_tokens": 0, "completion_tokens": 0}
        
        # combined_snippets 구성 시 언론사 출처 명시
        if not snippet_presses:
            snippet_presses = [f"기사{i+1}" for i in range(len(snippets))]
            
        combined_snippets = "\n\n".join([
            f"[{snippet_presses[i] if i < len(snippet_presses) else f'기사{i+1}'}]\n{s}"
            for i, s in enumerate(snippets)
        ])

        try:
            prompt = f"""
            당신은 뉴스 기사 본문을 분석하여 사건의 핵심 팩트를 정리하는 전문가입니다.
            아래 [기사 본문 근거]는 동일한 사건을 다룬 여러 언론사의 보도입니다.
            각 언론사의 본문에 공통으로 등장하는 팩트(사실관계)만 추출하여 정리하십시오.

            [기사 제목 목록]
            {titles[:10]} (총 {len(titles)}건)

            [기사 본문 근거 - 언론사별]
            {combined_snippets}

            [작성 규칙 - 절대 엄수]
            1. title: 반드시 아래 형식을 따른다.
               형식: "[사건명/의혹명], '[A 진영 핵심 입장]'-'[B 진영 핵심 입장]' [대립 강도]"
               → 앞부분: 사건의 핵심 키워드를 명사형으로 압축 (10자 내외)
               → 따옴표 안: 각 진영의 입장을 짧은 동사구로 압축 (8자 내외)
               → 대립 강도: '팽팽', '엇갈려', '충돌' 중 선택

            2. description: 아래 조건을 모두 만족하는 문장 4~6개로 구성한다.
                → 조건 1: [기사 본문 근거]의 1개 이상 언론사에 등장하는 팩트만 사용한다.
                → 조건 2: 특정 언론사의 주장·평가·논조가 아닌, 객관적 사실(날짜, 인물, 행위)만 담는다.
                → 조건 3: 반드시 [기사 본문 근거]에 실제로 있는 표현을 사용한다.
                → 조건 4: 반드시 포함할 항목:
                    ① 누가 언제 어디서 무엇을 공개했는지 (행위 주체, 일시, 장소)
                    ② 핵심 발언 직접 인용 (따옴표 포함 원문 그대로)
                    ③ 이 사건의 배경 (사건의 성격, 관련 의혹)
                    ④ 관련 인물의 법적 상태 (판결, 기소 여부)
                    ⑤ 상대방의 반박 입장

            3. background: 아래 조건을 모두 만족하는 문장 2~3개로 구성한다.
                → 조건 1: 이 사건이 왜 발생했는지, 무엇이 계기가 됐는지를 설명하는 팩트만 담는다.
                → 조건 2: [기사 본문 근거]에 실제로 있는 표현을 사용한다.
                → 조건 3: 수동형("~이 제기됐다") 대신 능동형("[주체]가 ~했다")으로 쓴다.
                → 조건 4: 반드시 포함할 항목:
                    ① 핵심 행위 주체가 무엇을 공개·제기했는지 (사건명 포함)
                    ② 공개된 내용의 핵심 정황 또는 의혹의 성격
                    ③ 이 사건이 어떤 더 큰 맥락(재판, 수사, 정치적 상황)과 연결되는지

            4. 할루시네이션 방지:
               → [기사 본문 근거]에 없는 인물명, 날짜, 발언, 사실을 절대 추가하지 마라.
               → 불확실하면 해당 내용을 생략하라.

            [응답 예시]
            {{
                "title": "쌍방울 진술회유 의혹, '녹취록 공개'-'국정조사' 팽팽",
                "description": "민주당은 29일 국회 기자간담회를 열고 2023년 6월 19일 박 검사와 이화영 전 경기도 부지사 변호인이었던 서민석 변호사의 통화 녹취 일부를 공개했다. 박 검사는 서 변호사에게 "이재명 씨가 완전히 주범이 되고 이 사람(이화영)이 종범이 되는 식의 자백이 있어야 저희가 그거를 할 수가 있고, 보석으로 나가는 거라든지 추가 영장을 안 한다든지 다 가능해지는 것"이라고 말했다. 이 전 부지사는 지난해 6월 대법원에서 뇌물 혐의로 징역 7년 8월을 확정받았다. 이 대통령의 제3자뇌물 혐의 사건 재판은 대통령의 불소추특권으로 정지됐다. 박 검사는 '녹취는 짜깁기되어 마치 역으로 제가 제안한 것처럼 둔갑되어 있다'며 서민석 변호사 본인이 이화영 종범 의율 제안을 한 녹취를 공개하라고 반발했다. 민주당은 향후 국정조사에서 전체 녹취가 공개될 것이라는 입장이다.",
                "background": "더불어민주당이 쌍방울 대북송금 사건을 수사한 박상용 검사의 '진술 회유' 정황이 담긴 녹취록을 공개해 파문이 일고 있다. 공개된 녹취에는 박 검사가 이재명 대통령을 주범으로 지목하는 자백을 해야 이화영 전 부지사에게 선처가 가능하다는 내용이 담겼다."
            }}
            """
            
            response_schema = {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "background": {"type": "string"}
                },
                "required": ["title", "description", "background"]
            }
            
            # call_llm은 utils.py에 정의된 공통 함수를 사용합니다. (반환: 결과, 토큰정보)
            parsed, usage = call_llm(prompt=prompt, model_size="local", state=state, schema=response_schema)
            
            if parsed:
                def to_str(val):
                    if isinstance(val, list):
                        return " ".join([str(v) for v in val])
                    return str(val) if val else ""

                return (
                    to_str(parsed.get("title", titles[0])), 
                    to_str(parsed.get("description", "이슈 요약 부재")),
                    to_str(parsed.get("background", "배경 정보 부재")),
                    usage
                )
            return titles[0], "요약 생성 실패", "배경 부재", empty_usage
        except Exception as e:
            logger.error(f"Issue LLM labeling failed: {e}")
            return titles[0], "에러 발생", "배경 부재", empty_usage

    # ==========================================
    # Graph Nodes
    # ==========================================
    @traceable(name="Agent 0: Cluster (미분류 기사 로드) 📂")
    def node_fetch_unclustered(self, state: dict) -> Dict[str, Any]:
        """미분류 기사 로드"""
        log_llm_event("ClusterAgent", "미분류 기사 로드 노드 시작")
        try:
            article_mode = state.get("article_mode", "editorial")
            self.db.rollback()
            unclustered = self.repo.get_unclustered_articles(article_type=article_mode)
            data = []
            for a in unclustered:
                content = a.body.raw_content if hasattr(a, 'body') and a.body else ""
                data.append({
                    'article_id': a.id,
                    'title': a.title,
                    'content': content,
                    'press': a.publisher.name if a.publisher else "알수없음",
                    'published_at': a.published_at  # 언론사별 최신 기사 우선 선택용
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
                distance_threshold = 1.1 # TODO 배포시 0.8로 변경
            
            custom_stopwords = ['기자', '특파원', '대해', '밝혔다', '관련', '오늘', '오후', '오전', '대통령', '대표', '의원', '민주당', '국민의힘', '한동훈', '이재명', '윤석열', '여야', '국회']
            vectorizer = TfidfVectorizer(max_features=5000, stop_words=custom_stopwords, ngram_range=(1, 2))
            X = vectorizer.fit_transform(docs)
            
            # 2. 계층적 군집화 수행
            from sklearn.metrics.pairwise import cosine_distances
            distance_matrix = cosine_distances(X)
            
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
                
                # 품질 조건 (정치 기사는 3곳 이상, 사설은 2곳 이상)
                min_articles = 3 if article_mode == "politics" else 2
                min_press = 2 if article_mode == "editorial" else 3
                
                # 사설의 경우 언론사 쏠림 방지 조건을 느슨하게 하거나 없앱니다 (1.0 = 제한 없음).
                max_ratio_limit = 0.6 if article_mode == "politics" else 1.0
                
                # 노이즈 체크 (코너명 반복 등)
                is_noise = self._is_noise_cluster(topic_articles['title'].tolist(), article_mode)
                
                if not is_noise and count >= min_articles and unique_press >= min_press and max_press_ratio <= max_ratio_limit:
                    # 언론사별 대표 기사 1개씩 선택 (최신 기사 우선)
                    # published_at이 없으면 원래 순서 유지
                    if 'published_at' in topic_articles.columns:
                        representative = (
                            topic_articles.sort_values('published_at', ascending=False)
                            .groupby('press').first().reset_index()
                        )
                    else:
                        representative = topic_articles.groupby('press').first().reset_index()

                    intermediate_topics.append({
                        "topic_id": int(topic_id),
                        # count와 press_count를 실제 저장 기사(언론사별 1개) 기준으로 통일
                        "count": int(len(representative)),
                        "press_count": int(len(representative)),
                        "titles": representative['title'].tolist(),  # 대표 기사 제목만 사용
                        "snippets": [
                            self._extract_snippet(row['content'])
                            for _, row in representative.iterrows()
                        ],
                        "snippet_presses": representative['press'].tolist(),
                        # ✅ article_ids도 언론사별 1개만 저장 (중복 언론사 방지)
                        "article_ids": representative['article_id'].tolist(),
                        "presses": representative['press'].tolist()
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

        article_mode = state.get("article_mode", "editorial")
        logger.info(f"[ClusterAgent:Save] 입력 토픽 수: {len(topics)}건")

        saved_ids = []
        # 노드 내 토큰 누적용 로컬 변수 (state 직접 변이 방지)
        node_usage = {"prompt_tokens": 0, "completion_tokens": 0}

        try:
            for t in topics:
                time.sleep(0.5)
                # ✅ 4-tuple로 usage까지 받아서 로컬에서 누적, snippet_presses 전달
                ai_label, desc, bg, usage = self._generate_issue_details_with_llm(
                    t["titles"], 
                    t.get("snippets", []), 
                    state, 
                    snippet_presses=t.get("snippet_presses", [])
                )
                node_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                node_usage["completion_tokens"] += usage.get("completion_tokens", 0)
                
                issue = self.repo.save_issue_and_relations(
                    ai_label=ai_label,
                    description=desc,
                    count=t["count"],
                    article_ids_to_update=t["article_ids"],
                    background=bg,
                    issue_type=article_mode
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
            article_mode = state.get("article_mode", "editorial")
            # issue_label_id가 여전히 NULL인 기사들 조회
            outliers = self.repo.get_unclustered_articles(article_type=article_mode)
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
