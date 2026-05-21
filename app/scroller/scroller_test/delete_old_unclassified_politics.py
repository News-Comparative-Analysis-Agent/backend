import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
sys.stdout.reconfigure(encoding='utf-8')

from datetime import datetime, timedelta
import pytz
from app.core.database import SessionLocal
from app.domains.articles.models import Article, ArticleBody, ArticleClaim
from app.domains.drafts.models import DraftReference
from app.domains.users.models import User
from app.domains.publishers.models import Publisher
from app.domains.issues.models import IssueLabel
from app.domains.system.models import SystemSettings
from app.core.logger import logger

def delete_old_unclassified_politics_articles(days: int = 4, dry_run: bool = False) -> int:
    """
    4일(기본값) 이상 지난 미분류(issue_label_id == None) 정치 기사를 데이터베이스에서 안전하게 제거합니다.
    """
    db = SessionLocal()
    try:
        # KST 기준 시간 설정
        KST = pytz.timezone('Asia/Seoul')
        kst_now = datetime.now(pytz.utc).astimezone(KST).replace(tzinfo=None)
        cutoff_date = kst_now - timedelta(days=days)
        
        logger.info(f"🧹 [{kst_now.strftime('%Y-%m-%d %H:%M:%S')}] {days}일 이상 지난 미분류 정치 기사 조회 중... (기준 시점: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')})")
        
        # 1. 4일 이상 지난 미분류 정치 기사 쿼리
        query = (
            db.query(Article)
            .filter(
                Article.article_type == 'politics',
                Article.issue_label_id == None,
                Article.published_at < cutoff_date
            )
        )
        
        old_articles = query.all()
        count = len(old_articles)
        
        if count == 0:
            logger.info("✅ 정리할 오래된 미분류 정치 기사가 없습니다.")
            return 0
            
        logger.info(f"⚠️ 총 {count}개의 오래된 미분류 정치 기사가 발견되었습니다.")
        
        if dry_run:
            logger.info("🔍 [Dry-run 모드] 실제 삭제를 진행하지 않고 기사 목록만 출력합니다:")
            for a in old_articles[:15]:
                logger.info(f"  - [ID: {a.id}] {a.publisher.name if a.publisher else '알수없음'} | {a.published_at.strftime('%Y-%m-%d')} | '{a.title}'")
            if count > 15:
                logger.info(f"  ...외 {count - 15}건 더 있음")
            return count

        old_article_ids = [a.id for a in old_articles]
        
        # 2. 관련 데이터 선삭제 (외래키 제약조건 준수)
        logger.info("🗑️ 관련 데이터(본문, 클레임, 초안 참조) 선삭제 진행 중...")
        
        # 본문(ArticleBody) 삭제
        body_del = db.query(ArticleBody).filter(ArticleBody.article_id.in_(old_article_ids)).delete(synchronize_session=False)
        # 클레임(ArticleClaim) 삭제
        claim_del = db.query(ArticleClaim).filter(ArticleClaim.article_id.in_(old_article_ids)).delete(synchronize_session=False)
        # 초안 참조(DraftReference) 삭제
        ref_del = db.query(DraftReference).filter(DraftReference.article_id.in_(old_article_ids)).delete(synchronize_session=False)
        
        logger.info(f"  - 삭제 완료: 본문 {body_del}건, 분석 카드 {claim_del}건, 초안 참조 {ref_del}건")
        
        # 3. 기사 메타데이터(Article) 최종 삭제
        deleted_count = db.query(Article).filter(Article.id.in_(old_article_ids)).delete(synchronize_session=False)
        
        db.commit()
        logger.info(f"✨ 성공적으로 {deleted_count}개의 오래된 미분류 정치 기사를 영구 삭제했습니다!")
        return deleted_count
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ 기사 정리 중 오류 발생: {e}")
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="4일 이상 지난 미분류 정치 기사 안전 정리 스크립트")
    parser.add_argument("--days", type=int, default=4, help="삭제할 기준 기간 (기본값: 4일)")
    parser.add_argument("--dry-run", action="store_true", help="실제 삭제하지 않고 대상 조회 및 목록만 확인")
    parser.add_argument("--yes", action="store_true", help="수락 확인 대기 질문 생략")
    args = parser.parse_args()
    
    if args.dry_run:
        delete_old_unclassified_politics_articles(days=args.days, dry_run=True)
    elif args.yes:
        delete_old_unclassified_politics_articles(days=args.days, dry_run=False)
    else:
        # 대상 미리 확인을 위해 드라이런 먼저 수행
        targets = delete_old_unclassified_politics_articles(days=args.days, dry_run=True)
        if targets > 0:
            confirm = input(f"\n⚠️ 실제로 {targets}개의 기사 및 관련 데이터를 삭제하시겠습니까? (y/n): ")
            if confirm.lower() == 'y':
                delete_old_unclassified_politics_articles(days=args.days, dry_run=False)
            else:
                print("❌ 기사 정리가 취소되었습니다.")
        else:
            print("정리할 대상이 없어 종료합니다.")
