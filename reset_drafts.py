import sys, os
sys.path.append('c:\\4_1 capstone\\backend')
from app.core.database import SessionLocal
from app.domains.issues.models import IssueLabel
from app.domains.articles.models import Article # Base mapping을 위해 필요

db = SessionLocal()
try:
    issues = db.query(IssueLabel).filter(IssueLabel.pre_generated_draft != None).all()
    for i in issues:
        i.pre_generated_draft = None
    db.commit()
    print(f"Successfully reset {len(issues)} drafts.")
except Exception as e:
    db.rollback()
    print(f"Error: {e}")
finally:
    db.close()
