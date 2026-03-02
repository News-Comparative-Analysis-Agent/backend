# app/scroller/scroller_test/mock_user_scenario.py
import sys
import os

# 프로젝트 루트 경로 추가
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.core.database import SessionLocal
from app.scroller.service import ScrollerService
from app.domains.users.models import User

def mock_scenario():
    print("🧪 [Test] Mock User Scenario 시작 (Mode: Gemini Only)")
    db = SessionLocal()
    service = ScrollerService(db)
    
    try:
        # 1. Mock User 생성
        mock_email = "tester@example.com"
        existing_user = db.query(User).filter(User.email == mock_email).first()
        if not existing_user:
            new_user = User(email=mock_email, nickname="TestBot")
            db.add(new_user)
            db.commit()
            print(f"✅ Mock 유저 생성 완료: {mock_email}")
        else:
            print(f"ℹ️ 기존 Mock 유저 사용: {mock_email}")

        # 2. 크롤링 실행 (Gemini Only)
        print("\n=== [Step 1] 크롤링 실행 (gemini_only) ===")
        # 실제 데이터가 너무 많을 수 있으므로 주석으로 남기고, 테스트용으로 호출
        crawl_result = service.execute_news_crawling(mode="gemini_only")
        print(f"결과: {crawl_result.status}, {crawl_result.message}")
        print(f"저장된 기사: {crawl_result.saved_count}, 스킵됨: {crawl_result.skipped_count}")

        # 3. 클러스터링 실행 (Gemini Only)
        print("\n=== [Step 2] 클러스터링 및 이슈 생성 (gemini_only) ===")
        cluster_result = service.execute_clustering(mode="gemini_only")
        print(f"결과: {cluster_result.status}, {cluster_result.message}")
        print(f"생성된 이슈 수: {cluster_result.saved_issue_count}")

        print("\n🏁 [Test] 모든 테스트 시나리오가 성공적으로 종료되었습니다.")
        
    except Exception as e:
        print(f"\n❌ [Test] 에러 발생: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    mock_scenario()
