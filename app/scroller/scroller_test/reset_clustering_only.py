from app.core.database import SessionLocal
from app.domains.articles.models import Article, ArticleClaim
from app.domains.issues.models import IssueLabel
from app.core.logger import logger

def reset_clustering():
    db = SessionLocal()
    try:
        logger.info("🧹 클러스터링 상태 초기화 시작...")

        # 1. 기사들의 이슈 연결 해제 (unclustered 상태로 복원)
        articles_updated = db.query(Article).update({Article.issue_label_id: None})
        logger.info(f"✅ {articles_updated}개의 기사를 미분류 상태로 복원했습니다.")

        # 2. 관련 주장(Claim) 카드 데이터 삭제
        claims_deleted = db.query(ArticleClaim).delete()
        logger.info(f"✅ {claims_deleted}개의 분석 데이터(Claim)를 삭제했습니다.")

        # 3. 이슈(IssueLabel) 데이터 삭제
        issues_deleted = db.query(IssueLabel).delete()
        logger.info(f"✅ {issues_deleted}개의 이슈(Cluster)를 삭제했습니다.")

        db.commit()
        logger.info("✨ 클러스터링 초기화가 완료되었습니다!")
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ 초기화 중 오류 발생: {e}")
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="클러스터링 결과만 초기화 (기사는 유지)")
    parser.add_argument("--yes", action="store_true", help="수락 확인 절차 생략")
    args = parser.parse_args()
    
    if args.yes:
        reset_clustering()
    else:
        confirm = input("[Confirm] 기사는 유지하고 클러스터링 결과(이슈, 분석 데이터)만 삭제합니다. 진행하시겠습니까? (y/n): ")
        if confirm.lower() == 'y':
            reset_clustering()
        else:
            print("초기화를 취소했습니다.")
