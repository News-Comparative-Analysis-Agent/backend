from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List
from app.domains.keywordrelation.models import KeywordRelation

class KeywordRelationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_relations_by_issue_ids(self, issue_ids: List[int]) -> List[KeywordRelation]:
        """여러 이슈 ID에 포함된 모든 관계 조회"""
        return self.db.query(KeywordRelation)\
            .filter(KeywordRelation.issue_label_id.in_(issue_ids))\
            .all()

    def get_relations_by_keyword(self, keyword: str) -> List[KeywordRelation]:
        """특정 키워드가 포함된 모든 관계 조회"""
        return self.db.query(KeywordRelation)\
            .filter((KeywordRelation.keyword_a == keyword) | (KeywordRelation.keyword_b == keyword))\
            .all()

    def get_mention_stats_by_keyword(self, keyword: str) -> List:
        """특정 키워드의 일자별 언급량(빈도 합계) 통계 조회"""
        return self.db.query(
            KeywordRelation.date,
            func.sum(KeywordRelation.frequency).label("total_count")
        ).filter(
            (KeywordRelation.keyword_a == keyword) | (KeywordRelation.keyword_b == keyword)
        ).group_by(
            KeywordRelation.date
        ).order_by(
            KeywordRelation.date.asc()
        ).all()
