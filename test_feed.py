import sys
import os

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

from app.core.database import SessionLocal
from app.domains.issues.service import IssueService
import json

def test_feed():
    db = SessionLocal()
    try:
        service = IssueService(db)
        # Fetch the feed
        feed = service.get_issue_feed(page=1, page_size=2)
        
        print(f"Today's Articles: {feed.today_article_count}")
        print(f"Today's Issues: {feed.today_issue_count}")
        print(f"Total Issues in feed: {feed.total_count}")
        
        for issue in feed.issues:
            print(f"\n--- Issue: {issue.name} (Count: {issue.article_count}) ---")
            for idx, article in enumerate(issue.articles):
                print(f"  [{idx+1}] {article.publisher} - {article.title}")
            
    finally:
        db.close()

if __name__ == "__main__":
    test_feed()
