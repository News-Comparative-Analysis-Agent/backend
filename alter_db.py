import os
import sys

# 프로젝트 루트 경로를 PATH에 추가
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from sqlalchemy import inspect, text
from app.core.database import engine, Base
from app.domains.issues.models import IssueLabel

def upgrade_schema():
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns('issue_labels')]
    
    print("현재 issue_labels 테이블의 컬럼:", columns)
    
    missing_columns = []
    
    # 모델에 정의되어 있지만 DB에 없는 컬럼들을 자동으로 추가합니다
    model_columns = IssueLabel.__table__.columns
    
    with engine.begin() as conn:
        for col in model_columns:
            if col.name not in columns:
                missing_columns.append(col.name)
                # 컬럼 타입 추출
                col_type = col.type.compile(engine.dialect)
                print(f"[{col.name}] 컬럼 추가 중... (타입: {col_type})")
                conn.execute(text(f"ALTER TABLE issue_labels ADD COLUMN {col.name} {col_type}"))
    
    if not missing_columns:
        print("모든 컬럼이 이미 존재합니다.")
    else:
        print("성공적으로 컬럼을 추가했습니다:", missing_columns)

if __name__ == "__main__":
    upgrade_schema()
