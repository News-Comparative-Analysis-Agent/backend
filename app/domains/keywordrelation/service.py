from sqlalchemy.orm import Session
from typing import List
from collections import defaultdict
from app.domains.issues.models import IssueLabel
from app.domains.keywordrelation.models import KeywordRelation
from app.domains.keywordrelation.schemas import GraphData, GraphNode, GraphLink

class KeywordRelationService:
    def __init__(self, db: Session):
        self.db = db

    def get_trend_graph(self, limit: int = 10) -> GraphData:
        """
        상위 N개 트렌드 이슈의 통합 키워드 관계도 분석 및 조회
        """
        # 1. 분석 대상이 될 상위 트렌드 이슈 조회
        top_issues = self.db.query(IssueLabel)\
            .order_by(IssueLabel.total_count.desc())\
            .limit(limit)\
            .all()
        
        if not top_issues:
            return GraphData(nodes=[], links=[])

        issue_ids = [issue.id for issue in top_issues]
        
        # 2. 해당 이슈들의 원천 키워드 관계 데이터 추출
        relations = self.db.query(KeywordRelation)\
            .filter(KeywordRelation.issue_label_id.in_(issue_ids))\
            .all()

        # 3. 네트워크 데이터 통합 분석 (중복 제거 및 빈도 합산)
        all_keywords = set()
        for issue in top_issues:
            if issue.keyword:
                all_keywords.update(issue.keyword)

        link_map = defaultdict(int)
        for rel in relations:
            # 무향 그래프 처리를 위한 정렬된 키 생성
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
