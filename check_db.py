import sys
import os
from dotenv import load_dotenv

# Set up environment
sys.path.append('.')
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)

from app.core.database import SessionLocal
from app.domains.articles.models import Article
from app.domains.issues.models import IssueLabel
from sqlalchemy import desc

def check_latest_data():
    db = SessionLocal()
    try:
        print("=== 최근 저장된 기사 (Articles) ===")
        latest_articles = db.query(Article).order_by(desc(Article.published_at)).limit(5).all()
        if not latest_articles:
            print("저장된 기사가 없습니다.")
        for art in latest_articles:
            print(f"- [{art.published_at}] {art.title} (Publisher: {art.publisher.name if getattr(art, 'publisher', None) else 'Unknown'})")
            
        print("\n=== 최근 저장된 이슈 (Issues) ===")
        latest_issues = db.query(IssueLabel).order_by(desc(IssueLabel.created_at)).limit(5).all()
        if not latest_issues:
            print("저장된 이슈가 없습니다.")
        for issue in latest_issues:
            print(f"- [{issue.created_at}] 이슈 ID: {issue.id} | 이름: {issue.name}")
            
    except Exception as e:
        print(f"DB 조회 중 오류 발생: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    check_latest_data()
