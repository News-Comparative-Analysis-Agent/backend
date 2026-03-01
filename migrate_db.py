import sys
import os
from dotenv import load_dotenv

# Set up environment
sys.path.append('.')
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)

from app.core.database import engine
from sqlalchemy import text

def add_columns():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE issue_labels ADD COLUMN background TEXT;"))
            print("background 칼럼 추가 완료")
        except Exception as e:
            print("background 칼럼이 이미 있거나 에러:", e)
            
        try:
            conn.execute(text("ALTER TABLE issue_labels ADD COLUMN core_contentions TEXT;"))
            print("core_contentions 칼럼 추가 완료")
        except Exception as e:
            print("core_contentions 칼럼이 이미 있거나 에러:", e)
            
        try:
            conn.execute(text("ALTER TABLE issue_labels ADD COLUMN media_ratio VARCHAR;"))
            print("media_ratio 칼럼 추가 완료")
        except Exception as e:
            print("media_ratio 칼럼이 이미 있거나 에러:", e)
            
        conn.commit()
        print("모든 칼럼 마이그레이션 완료!")

if __name__ == "__main__":
    add_columns()
