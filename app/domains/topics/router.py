from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.domains.topics.service import TopicService
from app.domains.topics.schemas import TopicResponse

router = APIRouter()

# @router.get("/daily-trends", 
#             response_model=List[TopicResponse],
#             summary="주요 정책/주제별 트렌드 조회",
#             description="현재 주목받고 있는 주요 대주제(의대 증원, 반도체 등) 목록을 가져옵니다.")
# def get_daily_trends(db: Session = Depends(get_db)):
#     """
#     일별 트렌드/이슈 목록 조회 API
#     - return: 토픽 리스트 (id, name, keywords, graph_data 포함)
#     """
#     service = TopicService(db)
#     return service.get_daily_trends()
