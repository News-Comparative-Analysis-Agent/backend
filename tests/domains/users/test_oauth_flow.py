from app.domains.users.schemas import UserCreate
from app.domains.users.service import UserService

# 이 파일은 OAuth 가입 및 로그인 시나리오 테스트를 위한 파일입니다.
def test_oauth_flow(db_session):
    """
    OAuth 가입 및 로그인 시나리오 테스트
    1. 신규 유저 가입 (Register)
    2. 기존 유저 로그인 (Login)
    """
    service = UserService(db_session)
    
    # [Step 1] 신규 유저 정보 (Google 로그인 가정)
    new_user_data = UserCreate(
        email="test@example.com",
        nickname="Tester",
        provider="google",
        provider_id="1234567890"
    )
    
    # 1. 가입 시도 (없으면 생성)
    created_user = service.get_or_create_user(new_user_data)
    
    # 검증: ID가 할당되어야 하고, DB에 저장되어야 함
    assert created_user.id is not None
    assert created_user.email == "test@example.com"
    assert created_user.provider == "google"
    print(f"\n[Test] User Created: ID={created_user.id}, Email={created_user.email}")

    # [Step 2] 동일한 정보로 재로그인 시도
    login_user = service.get_or_create_user(new_user_data)
    
    # 검증: 새로 생성하지 않고 기존 유저를 반환해야 함 (ID가 같아야 함)
    assert login_user.id == created_user.id
    assert login_user.email == created_user.email
    print(f"[Test] User Login: ID={login_user.id} (Matches Created ID)")
