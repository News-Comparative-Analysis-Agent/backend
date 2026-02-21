from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from app.core.database import get_db
from app.domains.articles.models import Article
from app.domains.publishers.models import Publisher

router = APIRouter()

class ImageItem(BaseModel):
    url: str
    title: str
    publisher: str
    published_at: str

@router.get("/images/{issue_id}", response_model=List[ImageItem])
async def get_issue_images(issue_id: int, db: Session = Depends(get_db)):
    """
    특정 이슈(issue_id)와 관련된 기사들의 이미지를 가져옵니다.
    """
    # 1. 해당 이슈 ID를 가진 기사들을 조회 (언론사 정보 포함)
    articles = db.query(Article).join(Publisher).filter(Article.issue_label_id == issue_id).all()
    
    if not articles:
        return []

    images = []
    seen_urls = set()

    # 2. 각 기사의 이미지 URL을 추출하여 리스트로 변환
    for art in articles:
        # article.image_urls는 문자열 리스트(ARRAY(Text))입니다.
        if art.image_urls:
            for url in art.image_urls:
                # 중복된 이미지 URL 제거 및 유효성 검사
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    images.append(ImageItem(
                        url=url,
                        title=art.title,
                        publisher=art.publisher.name,
                        published_at=art.published_at.strftime("%Y-%m-%d") if art.published_at else ""
                    ))
    
    return images
