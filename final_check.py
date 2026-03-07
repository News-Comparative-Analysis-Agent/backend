import sys, os
sys.path.append('c:\\4_1 capstone\\backend')
from app.core.database import SessionLocal
from app.domains.issues.models import IssueLabel
from app.domains.articles.models import Article

db = SessionLocal()
# 최근 생성된(혹은 방금 생성된) 초안을 가져옵니다.
issues = db.query(IssueLabel).filter(IssueLabel.pre_generated_draft != None).order_by(IssueLabel.id.desc()).all()

print(f"Total Drafted Issues: {len(issues)}")
for i in issues:
    print("=" * 100)
    print(f"ISSUE ID: {i.id} | TITLE: {i.name}")
    print("-" * 100)
    print(i.pre_generated_draft)
    print("=" * 100)
    print("\n\n")
