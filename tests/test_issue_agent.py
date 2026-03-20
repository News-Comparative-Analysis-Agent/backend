import os
import json
import pytest
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.agents.issue import IssueAgent
from app.scroller.repository import ScrollerRepository
from app.domains.issues.models import IssueLabel

# ==========================================
# 1. 데이터 로드 유틸리티
# ==========================================
@pytest.fixture(scope="module")
def issue_payload_items():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(current_dir, 'test_issue_data.json')
    if not os.path.exists(data_path):
        return []
    with open(data_path, 'r', encoding='utf-8') as f:
        return json.load(f)

@pytest.fixture(scope="module")
def db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==========================================
# 2. 통합 테스트 시나리오
# ==========================================
def test_issue_agent_integration(db: Session, issue_payload_items):
    if not issue_payload_items:
        pytest.skip("test_issue_data.json not found")

    repo = ScrollerRepository(db)
    # IssueAgent는 DB 세션을 주입받아 IssueRepository를 내부적으로 생성함
    agent = IssueAgent(db)
    
    # A. 시스템 LLM 모드 확인
    settings = repo.get_system_settings()
    llm_mode = settings.llm_mode
    print(f"\n[INFO] 현재 시스템 LLM 모드: {llm_mode}")

    # B. 테스트용 초기 데이터 생성 (IssueLabel)
    # IssueAgent.node_structure_issues는 DB에서 이슈 정보를 가져오므로 미리 생성 필요
    test_issue = IssueLabel(
        name="[TEST] 국힘 대구 공천 갈등",
        description="국민의힘 대구 공천 과정에서의 갈등 분석",
        background="호남 출신 공관위원장에 대한 반발로 시작된 논란"
    )
    db.add(test_issue)
    db.commit() # ID 확정
    print(f"[INFO] 테스트 이슈(ID: {test_issue.id}) 생성 완료")

    try:
        # C. IssueAgent 실행
        state = {
            "issue_id": test_issue.id,
            "llm_mode": llm_mode,
            "issue_payload_items": issue_payload_items,
            "total_tokens": {"prompt_tokens": 0, "completion_tokens": 0}
        }

        print(f"[STEP] node_structure_issues 실행 중... (Mode: {llm_mode})")
        result = agent.node_structure_issues(state)
        
        # D. 결과 검증
        print("\n[RESULT] 생성된 분석 데이터:")
        print(f"  - Conflict Summary: {result.get('conflict_summary')}")
        print(f"  - Final Media Views 개수: {len(result.get('media_views', []))}")
        
        assert result.get("conflict_summary") is not None
        assert len(result.get("media_views", [])) == 2
        
        # 각 매체별 서술(narrative)이 생성되었는지 확인
        for i, mv in enumerate(result["media_views"]):
            print(f"    {i+1}. [{mv['press']}] Narrative: {mv.get('narrative')}")
            assert mv.get("narrative") != ""

        print("\n[SUCCESS] IssueAgent 통합 테스트 완료")

    finally:
        # E. 테스트 데이터 정리
        print("[CLEANUP] 테스트 데이터 삭제 중...")
        db.query(IssueLabel).filter(IssueLabel.id == test_issue.id).delete()
        db.commit()
        print("[CLEANUP] 완료")

if __name__ == "__main__":
    pytest.main([__file__, "-s"])
