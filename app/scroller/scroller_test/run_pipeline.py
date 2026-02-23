import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.core.database import SessionLocal
from app.scroller.service import ScrollerService

def run_daily_pipeline():
    print("🚀 [Pipeline] 뉴스 크롤링 및 이슈 클러스터링 자동화 파이프라인 시작합니다...")
    db = SessionLocal()
    service = ScrollerService(db)
    
    try:
        # 1. 크롤링 실행
        print("\n=== 1단계: 크롤링 및 구형 데이터 삭제 ===")
        crawl_result = service.execute_news_crawling()
        print(f"결과: {crawl_result.message}")
        
        # 2. 클러스터링 실행
        print("\n=== 2단계: 미분류 기사 이슈 클러스터링 ===")
        cluster_result = service.execute_clustering()
        print(f"결과: {cluster_result.message}")
        
        print("\n🎉 [Pipeline] 모든 파이프라인이 성공적으로 종료되었습니다.")
        
    except Exception as e:
        print(f"\n❌ [Pipeline] 파이프라인 오류 발생: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    run_daily_pipeline()
