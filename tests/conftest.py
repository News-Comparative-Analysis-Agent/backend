import pytest
from app.core.database import SessionLocal, Base, engine

@pytest.fixture(scope="session")
def db_engine():
    # 테스트 전용 DB 테이블 생성
    Base.metadata.create_all(bind=engine)
    yield engine
    # Base.metadata.drop_all(bind=engine)

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
    transaction.rollback()
    # transaction.commit()
    connection.close()
