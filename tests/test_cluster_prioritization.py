import sys
import os
import pandas as pd
import unittest

# 프로젝트 루트 디렉토리를 sys.path에 추가
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

class TestClusterPrioritization(unittest.TestCase):
    def setUp(self):
        self.priority_press = ["한겨레", "조선일보", "경향신문", "한국일보"]

    def test_editorial_prioritization_and_limit(self):
        """사설 모드에서 주요 언론사 우선순위 및 4개 제한 로직 검증"""
        
        # 1. 테스트 데이터 준비 (6개 매체)
        # 1, 2, 3번은 주요 언론사 / 4, 5, 6번은 일반 매체
        # 6번 매체가 가장 최신임
        data = [
            {"article_id": 1, "press": "조선일보", "title": "조선일보 기사", "published_at": "2024-05-01 10:00:00"},
            {"article_id": 2, "press": "한겨레", "title": "한겨레 기사", "published_at": "2024-05-01 09:00:00"},
            {"article_id": 3, "press": "한국일보", "title": "한국일보 기사", "published_at": "2024-05-01 08:00:00"},
            {"article_id": 4, "press": "일반1", "title": "일반1 기사", "published_at": "2024-05-01 07:00:00"},
            {"article_id": 5, "press": "일반2", "title": "일반2 기사", "published_at": "2024-05-01 06:00:00"},
            {"article_id": 6, "press": "일반3", "title": "일반3 기사", "published_at": "2024-05-01 11:00:00"}, # 가장 최신
        ]
        topic_articles = pd.DataFrame(data)
        article_mode = "editorial"
        
        # 2. 로직 실행 (ClusterAgent의 내부 정렬 및 제한 로직 시뮬레이션)
        PRIORITY_PRESS = self.priority_press
        
        temp_df = topic_articles.copy()
        temp_df['is_priority'] = temp_df['press'].apply(lambda x: x in PRIORITY_PRESS)
        
        # 언론사별 대표 선택 (우선순위 + 최신순)
        representative = (
            temp_df.sort_values(['is_priority', 'published_at'], ascending=[False, False])
            .groupby('press').first().reset_index()
        )
        
        # 전체 결과 정렬 유지
        representative['is_priority'] = representative['press'].apply(lambda x: x in PRIORITY_PRESS)
        representative = representative.sort_values(['is_priority', 'published_at'], ascending=[False, False])
        
        # 4개 제한 적용
        if article_mode == "editorial" and len(representative) > 4:
            representative = representative.head(4)
            
        # 3. 결과 검증
        selected_presses = representative['press'].tolist()
        print(f"\n[Scenario 1] 선정된 언론사: {selected_presses}")
        
        # 주요 언론사 3곳이 포함되었는지 확인
        for press in ["조선일보", "한겨레", "한국일보"]:
            self.assertIn(press, selected_presses)
            
        # 나머지 1자리는 주요 언론사가 아닌 것 중 가장 최신인 '일반3'이어야 함
        self.assertIn("일반3", selected_presses)
        self.assertEqual(len(selected_presses), 4)

    def test_fallback_to_latest_when_no_priority(self):
        """주요 언론사가 없을 때 최신순으로 4개 뽑는지 검증"""
        
        # 모든 매체가 일반 매체인 상황 (6개)
        data = [
            {"article_id": 1, "press": "일반1", "published_at": "2024-05-01 01:00:00"},
            {"article_id": 2, "press": "일반2", "published_at": "2024-05-01 06:00:00"},
            {"article_id": 3, "press": "일반3", "published_at": "2024-05-01 03:00:00"},
            {"article_id": 4, "press": "일반4", "published_at": "2024-05-01 05:00:00"},
            {"article_id": 5, "press": "일반5", "published_at": "2024-05-01 04:00:00"},
            {"article_id": 6, "press": "일반6", "published_at": "2024-05-01 02:00:00"},
        ]
        topic_articles = pd.DataFrame(data)
        article_mode = "editorial"
        PRIORITY_PRESS = self.priority_press
        
        temp_df = topic_articles.copy()
        temp_df['is_priority'] = temp_df['press'].apply(lambda x: x in PRIORITY_PRESS)
        
        representative = (
            temp_df.sort_values(['is_priority', 'published_at'], ascending=[False, False])
            .groupby('press').first().reset_index()
        )
        representative['is_priority'] = representative['press'].apply(lambda x: x in PRIORITY_PRESS)
        representative = representative.sort_values(['is_priority', 'published_at'], ascending=[False, False])
        
        if article_mode == "editorial" and len(representative) > 4:
            representative = representative.head(4)
            
        selected_presses = representative['press'].tolist()
        print(f"[Scenario 2] 주요 언론사 없을 때 선정 결과: {selected_presses}")
        
        # 최신순 상위 4개 (일반2, 일반4, 일반5, 일반3) 가 선정되어야 함
        expected = ["일반2", "일반4", "일반5", "일반3"]
        for press in expected:
            self.assertIn(press, selected_presses)
        self.assertEqual(len(selected_presses), 4)

if __name__ == "__main__":
    unittest.main()
