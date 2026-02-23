import sys
import os

# 현재 파일 위치: backend/app/scroller/scroller_test/reset_db_tool.py
# backend 폴더를 찾기 위해 부모 폴더로 4번 올라갑니다.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.core.database import SessionLocal
from app.scroller.service import ScrollerService

if __name__ == "__main__":
    print("⚠️ 데이터베이스 초기화(기사 및 이슈 관련 데이터 전부 삭제)를 시작합니다...")
    db = SessionLocal()
    try:
        service = ScrollerService(db)
        result = service.execute_truncate()
        print(f"\n[실행 완료] {result.status}")
        print(result.message)
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
    finally:
        db.close()
