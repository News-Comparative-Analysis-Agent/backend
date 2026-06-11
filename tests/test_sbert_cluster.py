import sys
import os
import unittest
from unittest.mock import MagicMock

# 프로젝트 루트 디렉토리를 sys.path에 추가
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from app.agents.cluster import ClusterAgent

class TestSBERTCluster(unittest.TestCase):
    def test_sbert_tfidf_hybrid_clustering(self):
        print("\n=== SBERT + TF-IDF 하이브리드 군집화 테스트 시작 ===")
        
        # 1. Mock DB 세션 생성
        mock_db = MagicMock()
        agent = ClusterAgent(mock_db)
        
        # 2. 테스트 데이터 정의
        # Group 1: 아이폰 및 스마트폰 가격 인상 관련 기사들
        # Group 2: 한국 프로야구(KBO) 한국시리즈 결승 관련 기사들
        articles = [
            {
                "article_id": 1,
                "press": "조선일보",
                "title": "애플, 다음달 신형 아이폰 가격 전격 인상 발표 예정",
                "content": "애플이 원자재 가격 상승과 공급망 교란을 이유로 다음달 출시될 차세대 아이폰 시리즈의 출고가를 최대 10% 인상하기로 결정했습니다. 특히 프로 모델의 인상폭이 클 것으로 보여 소비자들의 부담이 가중될 전망입니다.",
                "published_at": "2026-06-11 10:00:00"
            },
            {
                "article_id": 2,
                "press": "한겨레",
                "title": "스마트폰 출고가 또 오른다… 아이폰 가격 인상 조짐에 시끌",
                "content": "스마트폰 핵심 부품 가격 상승세가 지속되면서 애플이 아이폰 신제품 가격을 인상할 것이라는 예측이 나옵니다. 업계 관계자는 부품 원가 부담이 심화되어 가격 동결은 어려울 것이라고 전했습니다.",
                "published_at": "2026-06-11 10:05:00"
            },
            {
                "article_id": 3,
                "press": "경향신문",
                "title": "가계 통신비 부담 늘어나나… 차기 스마트폰 신작 가격 일제히 인상 전망",
                "content": "하반기 스마트폰 시장의 최대 관심사인 아이폰 신작의 출고가가 대폭 오를 것으로 보입니다. 고물가 기조 속에 가전 및 통신 기기 가격 인상이 이어지며 가계 경제에 미칠 영향에 대한 우려의 목소리가 커지고 있습니다.",
                "published_at": "2026-06-11 10:10:00"
            },
            {
                "article_id": 4,
                "press": "한국일보",
                "title": "KBO 한국시리즈 7차전 혈투 끝에 기아 타이거즈 우승 차지",
                "content": "2026 프로야구 신한 SOL뱅크 KBO 한국시리즈 최종 7차전에서 기아 타이거즈가 연장 11회말 극적인 끝내기 안타로 승리하며 통산 12번째 우승 트로피를 들어올렸습니다. 경기장을 메운 팬들은 환호했습니다.",
                "published_at": "2026-06-11 10:20:00"
            },
            {
                "article_id": 5,
                "press": "동아일보",
                "title": "기아 타이거즈, 기적의 역전승으로 프로야구 한국시리즈 패권 탈환",
                "content": "기아가 마침내 프로야구 챔피언 자리에 다시 올랐습니다. 기아 타이거즈는 한국시리즈 마지막 경기에서 짜릿한 뒤집기 승리를 거두며 우승을 갈망하던 팬들에게 최고의 선물을 안겼습니다. MVP는 결승타의 주인공에게 돌아갔습니다.",
                "published_at": "2026-06-11 10:25:00"
            },
            {
                "article_id": 6,
                "press": "중앙일보",
                "title": "한국시리즈의 왕자 기아 타이거즈, 연장전 접전 끝 최종 우승 달성",
                "content": "올해 프로야구 최고의 팀은 기아 타이거즈였습니다. 기아는 최종전에서 홈런 공방전 끝에 승리를 거머쥐며 한국시리즈 정상의 기쁨을 누렸습니다. 감독은 선수단과 팬들의 성원 덕분이라며 소감을 밝혔습니다.",
                "published_at": "2026-06-11 10:30:00"
            }
        ]
        
        state = {
            "unclustered_articles": articles,
            "article_mode": "politics",  # 최소 3개 매체 조건 적용됨
            "messages": []
        }
        
        # 3. 군집화 수행
        result = agent.node_lexical_cluster(state)
        
        # 4. 결과 출력 및 검증
        clustered_topics = result.get("clustered_topics", [])
        print(f"\n[결과] 도출된 클러스터 개수: {len(clustered_topics)}")
        
        for idx, topic in enumerate(clustered_topics):
            print(f"\n클러스터 #{idx+1} (기사 수: {topic['count']}):")
            print(f"  언론사: {topic['snippet_presses']}")
            print("  기사 제목들:")
            for title in topic["titles"]:
                print(f"    - {title}")
                
        # 두 개의 뚜렷한 주제군(아이폰 가격 인상군 vs 야구 우승군)으로 정상 분리되어 군집화되어야 합니다.
        self.assertEqual(len(clustered_topics), 2, "정상적인 군집화 하에서는 2개의 클러스터가 도출되어야 합니다.")
        
        # 각 군집에 매체가 최소 3개씩 들어갔는지 검증
        for topic in clustered_topics:
            self.assertEqual(topic['count'], 3, "각 군집은 3개의 언론사별 대표 기사를 가지고 있어야 합니다.")
            
        print("\n=== 테스트 완료: SBERT + TF-IDF 하이브리드 군집화 성공 ===")

if __name__ == "__main__":
    unittest.main()
