from sqlalchemy.orm import Session
from typing import List
from app.domains.topics.models import Topic

class TopicService:
    def __init__(self, db: Session):
        self.db = db

    def get_daily_trends(self) -> List[Topic]:
        """
        일별 트렌드/이슈 목록 조회
        - 현재는 DB에 저장된 모든 토픽을 반환합니다.
        - 추후 기사 수 집계나 그래프 데이터 생성 로직을 추가할 수 있습니다.
        """
        return self.db.query(Topic).all()
