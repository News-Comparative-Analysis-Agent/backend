from sqlalchemy.orm import Session
from typing import List
from app.domains.topics.models import Topic
from app.domains.topics.schemas import TopicResponse

class TopicService:
    def __init__(self, db: Session):
        self.db = db

    def get_daily_trends(self) -> List[Topic]:
        """
        일별 트렌드 목록 조회
        - 현재는 모든 Topic을 가져오지만, 추후 날짜별 필터링 추가 예정
        """
        return self.db.query(Topic).order_by(Topic.id.desc()).all()
