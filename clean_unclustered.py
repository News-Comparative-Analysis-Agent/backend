import sys
import os
from sqlalchemy.orm import Session
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.core.database import SessionLocal
from app.domains.articles.models import Article, ArticleBody

def clean():
    with SessionLocal() as db:
        # Find unclustered editorial articles
        unclustered = db.query(Article).filter(
            Article.issue_label_id == None,
            Article.article_type == 'editorial'
        ).all()
        
        if not unclustered:
            print("삭제할 미분류 사설 기사가 없습니다.")
            return
            
        unclustered_ids = [a.id for a in unclustered]
        print(f"총 {len(unclustered_ids)}건의 미분류 사설 기사를 삭제합니다...")
        
        # Delete bodies
        db.query(ArticleBody).filter(ArticleBody.article_id.in_(unclustered_ids)).delete(synchronize_session=False)
        
        # Delete articles
        deleted_count = db.query(Article).filter(Article.id.in_(unclustered_ids)).delete(synchronize_session=False)
        
        db.commit()
        print(f"삭제 완료: {deleted_count}건")

if __name__ == '__main__':
    clean()
