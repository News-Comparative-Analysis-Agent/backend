import sys
import os
from dotenv import load_dotenv

sys.path.append('.')
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)

from app.core.database import SessionLocal
from app.domains.issues.service import IssueService

def test():
    db = SessionLocal()
    try:
        service = IssueService(db)
        print("Fetching issue_id=3")
        res = service.get_issue_analysis(3)
        print("Success:", res.issue_name)
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    test()
