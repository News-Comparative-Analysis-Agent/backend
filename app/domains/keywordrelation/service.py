from sqlalchemy.orm import Session
from typing import List
from collections import defaultdict
from app.domains.issues.repository import IssueRepository
from app.domains.keywordrelation.repository import KeywordRelationRepository
from app.domains.keywordrelation.schemas import GraphData, GraphNode, GraphLink, KeywordMentionResponse, KeywordMentionPoint

class KeywordRelationService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = KeywordRelationRepository(db)
        self.issue_repo = IssueRepository(db)

    def get_trend_graph(self, limit: int = 10) -> GraphData:
        """
        상위 N개 트렌드 이슈의 통합 키워드 관계도 분석 및 조회
        """
        # 1. 선정된 상위 이슈 조회
        top_issues = self.issue_repo.get_top_issues(limit=limit)
        
        if not top_issues:
            return GraphData(nodes=[], links=[])

        issue_ids = [issue.id for issue in top_issues]
        
        # 2. 해당 이슈들의 원천 데이터 추출
        relations = self.repo.get_relations_by_issue_ids(issue_ids)

        # 3. 네트워크 데이터 통합 분석
        all_keywords = set()
        for issue in top_issues:
            if issue.keyword:
                all_keywords.update(issue.keyword)

        link_map = defaultdict(int)
        for rel in relations:
            pair = tuple(sorted([rel.keyword_a, rel.keyword_b]))
            link_map[pair] += rel.frequency
            all_keywords.add(rel.keyword_a)
            all_keywords.add(rel.keyword_b)

        # 4. 시각화 데이터 구조로 변환
        nodes = [GraphNode(id=kw) for kw in sorted(list(all_keywords))]
        links = [
            GraphLink(source=pair[0], target=pair[1], value=freq)
            for pair, freq in link_map.items()
        ]

        return GraphData(nodes=nodes, links=links)

    def get_keyword_graph(self, keyword: str) -> GraphData:
        """
        특정 키워드와 연관된 키워드 네트워크 조회 (1단계 Ego Network)
        """
        # 1. 특정 키워드 포함 관계 조회
        relations = self.repo.get_relations_by_keyword(keyword)
            
        if not relations:
            return GraphData(nodes=[GraphNode(id=keyword)], links=[])

        # 2. 통합 분석
        all_keywords = {keyword}
        link_map = defaultdict(int)
        
        for rel in relations:
            pair = tuple(sorted([rel.keyword_a, rel.keyword_b]))
            link_map[pair] += rel.frequency
            all_keywords.add(rel.keyword_a)
            all_keywords.add(rel.keyword_b)

        # 3. 시각화 데이터 구조로 변환
        nodes = [GraphNode(id=kw) for kw in sorted(list(all_keywords))]
        links = [
            GraphLink(source=pair[0], target=pair[1], value=freq)
            for pair, freq in link_map.items()
        ]

        return GraphData(nodes=nodes, links=links)

    def get_keyword_mentions(self, keyword: str) -> KeywordMentionResponse:
        """
        특정 키워드의 시계열 언급량 추이 조회
        """
        # 1. 일자별 빈도 합계 통계 조회
        mention_stats = self.repo.get_mention_stats_by_keyword(keyword)

        # 2. 결과 가공
        mentions = [
            KeywordMentionPoint(date=row.date, count=row.total_count)
            for row in mention_stats
        ]

        return KeywordMentionResponse(
            keyword=keyword,
            mentions=mentions
        )
