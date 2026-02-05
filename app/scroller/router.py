from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
from app.scroller.nlp_search import NewsBriefingAgent

router = APIRouter()

class SearchRequest(BaseModel):
    query: str

@router.post("/nlp")
async def search_news_nlp(request: SearchRequest):
    """
    NLP 기반 뉴스 검색 및 브리핑 API
    """
    agent = NewsBriefingAgent()
    result = agent.run(request.query)
    return result
