import pytest
from app.core.database import SessionLocal, Base, engine

# 이 파일은 테스트 코드를 실행시키는 파일입니다.

@pytest.fixture(scope="session")
def db_engine():
    # 0. 기존 테이블 초기화
    Base.metadata.drop_all(bind=engine)

    # 1. 테이블 생성
    # 테스트 전용 DB 테이블 생성
    Base.metadata.create_all(bind=engine)
    yield engine

@pytest.fixture(scope="function")
def db_session(db_engine):
    """
    각 테스트 함수마다 새로운 DB 세션을 생성하고,
    테스트가 끝나면 롤백하여 DB 상태를 유지합니다.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)

    yield session

    session.close()

    # 2. 테스트 후 롤백
    transaction.rollback()

    # 3. 테스트 후 커밋
    # transaction.commit()
    connection.close()

@pytest.fixture(scope="function")
def seeded_db_session(db_session):
    """
    기본 DB 세션에 Mock 데이터를 미리 채워넣은 세션을 반환합니다.
    데이터 조회/검색 API 테스트 시 사용합니다.
    """
    from .mockdata import insert_seed_data
    
    insert_seed_data(db_session)
    return db_session
