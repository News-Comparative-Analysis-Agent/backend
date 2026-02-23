import os
import sys

base_dir = r"c:\Users\imchangsu\OneDrive\바탕 화면\4_1 capstone\backend"
sys.path.append(base_dir)

files_to_del = ["clustering.py", "prompts.py", "ranking_scroller.py", "reset_db.py", "scheduler.py", "vpn_server.py"]
for f in files_to_del:
    try:
        os.remove(os.path.join(base_dir, "app", "scroller", f))
        print(f"Deleted {f}")
    except OSError:
        pass

print("Initializing database...")
from app.core.database import SessionLocal
from app.scroller.service import ScrollerService
db = SessionLocal()
service = ScrollerService(db)
service.execute_truncate()
db.close()

from app.scroller.scroller_test.run_pipeline import run_daily_pipeline
run_daily_pipeline()
