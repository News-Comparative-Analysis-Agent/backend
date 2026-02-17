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
    Fetches image URLs from articles related to the given issue ID.
    """
    # Join with Publisher to get publisher name
    articles = db.query(Article).join(Publisher).filter(Article.issue_label_id == issue_id).all()
    
    if not articles:
        return []

    images = []
    seen_urls = set()

    for art in articles:
        # article.image_urls is expected to be a list of strings (ARRAY(Text))
        if art.image_urls:
            for url in art.image_urls:
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    images.append(ImageItem(
                        url=url,
                        title=art.title,
                        publisher=art.publisher.name,
                        published_at=art.published_at.strftime("%Y-%m-%d") if art.published_at else ""
                    ))
    
    return images
