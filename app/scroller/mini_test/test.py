import sys
import os

# 현재 파일(test.py)의 위치에서 3단계 위로 올라가면 backend 폴더입니다.
# app 폴더가 들어있는 backend 경로를 sys.path에 추가해야 'from app...'이 작동합니다.
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
sys.path.append(backend_dir)

from app.core.database import SessionLocal
from app.domains.articles.models import Article, ArticleBody, ArticleClaim
from app.domains.issues.models import IssueLabel

def clear_db():
    db = SessionLocal()
    try:
        # 데이터베이스의 테이블들을 TRUNCATE하여 데이터를 지우고 ID(Sequence)도 1로 완전히 초기화
        # PostgreSQL 문법인 RESTART IDENTITY 활용 (SQLite라면 delete-sequence 방식 사용 등 필요)
        # SQLAlchemy Core의 text() 기능을 사용하여 Raw SQL 실행
        from sqlalchemy import text
        
        db.execute(text('TRUNCATE TABLE article_claim_card RESTART IDENTITY CASCADE;'))
        db.execute(text('TRUNCATE TABLE article_body RESTART IDENTITY CASCADE;'))
        db.execute(text('TRUNCATE TABLE articles RESTART IDENTITY CASCADE;'))
        db.execute(text('TRUNCATE TABLE issue_labels RESTART IDENTITY CASCADE;'))
        
        db.commit()
        
        print(f"✅ 데이터베이스 초기화(ID=1) 완료!")
        
    except Exception as e:
        db.rollback()
        print(f"❌ 데이터 삭제 중 오류 발생: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    clear_db()
