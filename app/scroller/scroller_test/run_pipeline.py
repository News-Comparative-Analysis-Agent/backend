import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.core.database import SessionLocal
from app.scroller.service import ScrollerService
from app.domains.system.models import SystemSettings

def run_daily_pipeline():
    print("🚀 [Pipeline] 뉴스 크롤링 및 이슈 클러스터링 자동화 파이프라인 시작합니다...")
    # 실행 전 초기 설정 데이터 확인 및 주입 (데이터 있으면 스킵됨)
    seed_settings()
    
    db = SessionLocal()
    service = ScrollerService(db)
    
    try:
        # 0. 글로벌 설정 확인 (관리자 모드)
        setting = db.query(SystemSettings).first()
        active_mode = setting.llm_mode if setting else "gemini_only"
        print(f"📡 [Settings] 현재 시스템 설정 모드: {active_mode}")

        # 1. 크롤링 실행
        print(f"\n=== 1단계: 크롤링 및 분석 (Mode: {active_mode}) ===")
        crawl_result = service.execute_news_crawling(mode=active_mode)
        print(f"결과: {crawl_result.message}")
        
        # 2. 클러스터링 실행
        print(f"\n=== 2단계: 클러스터링 및 이슈 명명 (Mode: {active_mode}) ===")
        cluster_result = service.execute_clustering(mode=active_mode)
        print(f"결과: {cluster_result.message}")
        
        print("\n🎉 [Pipeline] 모든 파이프라인이 성공적으로 종료되었습니다.")
        
    except Exception as e:
        print(f"\n❌ [Pipeline] 파이프라인 오류 발생: {e}")
    finally:
        db.close()

def seed_settings():
    """
    초기 시스템 설정(gemini_only) 주입 메서드
    크롤링 파이프라인 실행 전 실행
    """
    db = SessionLocal()
    try:
        existing = db.query(SystemSettings).first()
        if not existing:
            new_setting = SystemSettings(id=1, llm_mode="gemini_only")
            db.add(new_setting)
            db.commit()
            print("✅ 초기 시스템 설정(gemini_only) 주입 완료!")
        else:
            print(f"ℹ️ 기존 설정 유지 중: {existing.llm_mode}")
    finally:
        db.close()


if __name__ == "__main__":
    run_daily_pipeline()
