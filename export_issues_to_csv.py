import os
import csv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, joinedload
from app.core.database import SessionLocal
from app.domains.articles.models import Article, IssueLabel

def export_to_csv():
    db = SessionLocal()
    
    # 1. Fetch all issues descending
    issues = db.query(IssueLabel).order_by(IssueLabel.id.desc()).all()
    
    csv_file = "clustered_issues_report_v2.csv"
    with open(csv_file, mode='w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        # Header
        writer.writerow(['Issue ID', 'Issue Label', 'Article Count', 'Article Title', 'Article Content Snippet', 'Press Name', 'URL'])
        
        for issue in issues:
            # 2. Fetch articles for this issue
            articles = db.query(Article).options(joinedload(Article.publisher), joinedload(Article.body)).filter(Article.issue_label_id == issue.id).order_by(Article.id.desc()).all()
            
            if not articles:
                writer.writerow([issue.id, issue.name, issue.total_count, "", "", "", ""])
                continue
                
            for idx, article in enumerate(articles):
                press_name = article.publisher.name if article.publisher else "Unknown"
                content_snippet = article.body.raw_content[:150].replace('\n', ' ') + "..." if article.body and article.body.raw_content else ""
                
                row = [
                    issue.id if idx == 0 else "",
                    issue.name if idx == 0 else "",
                    issue.total_count if idx == 0 else "",
                    article.title,
                    content_snippet,
                    press_name,
                    article.url
                ]
                writer.writerow(row)
                
    print(f"✅ CSV Export Complete! -> {os.path.abspath(csv_file)}")
    
    # Check for specific weird items
    mb_articles = db.query(Article).options(joinedload(Article.publisher), joinedload(Article.body)).filter(Article.title.like('%이명박%')).all()
    print(f"\n🔍 [Debug] 제 목에 '이명박' 관련 기사가 총 {len(mb_articles)}건 발견되었습니다:")
    for a in mb_articles:
        press = a.publisher.name if a.publisher else "Unknown"
        print(f" - [{press}] {a.title} ({a.url})")
    
if __name__ == "__main__":
    export_to_csv()
