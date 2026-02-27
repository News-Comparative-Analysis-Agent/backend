from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from app.core.database import engine, Base, get_db

# 모든 도메인의 모델들을 임포트해야 Base.metadata가 모든 테이블을 인지합니다.
from app.domains.users import models as user_models
from app.domains.publishers import models as pub_models
from app.domains.articles import models as art_models
from app.domains.issues import models as issue_models
from app.domains.drafts import models as draft_models

router = APIRouter()

@router.delete("/reset-db")
def reset_database_api():
    """
    모든 테이블을 강제로 삭제하고 다시 생성합니다.
    """
    from sqlalchemy import text, inspect
    try:
        # 현재 연결된 DB 주소 확인 (디버깅용)
        db_info = f"연결된 DB: {engine.url.render_as_string(hide_password=True)}"
        print(db_info)
        
        # 1. 실제 DB에서 모든 테이블 이름 가져오기
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        print(f"삭제 전 발견된 테이블: {table_names}")

        # 2. 강제 삭제 (MetaData에 없는 테이블이나 외래키 관계 무시를 위해 CASCADE 사용)
        with engine.connect() as conn:
            # PostgreSQL 전용 강제 삭제 로직
            for table in table_names:
                conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE;'))
            conn.commit()
            print("모든 테이블 강제 삭제 완료 (CASCADE 적용)")
        
        # 3. 새로운 테이블 생성 (MetaData 기반)
        print("최신 모델 구조로 테이블 생성 시작...")
        Base.metadata.create_all(bind=engine)
        
        # 4. 생성 후 확인
        new_tables = inspect(engine).get_table_names()
        print(f"생성 후 테이블 목록: {new_tables}")
        
        return {
            "status": "success", 
            "db_url": db_info,
            "deleted": table_names,
            "created": new_tables
        }
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"DB 초기화 중 에러 발생:\n{error_trace}")
        raise HTTPException(status_code=500, detail=f"DB 초기화 실패: {str(e)}")
