import os
import json
import pytest
from app.agents.editor import EditorAgent

# ==========================================
# 1. 데이터 로드 유틸리티
# ==========================================
@pytest.fixture(scope="module")
def editor_input():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(current_dir, 'test_editor_data.json')
    if not os.path.exists(data_path):
        return {}
    with open(data_path, 'r', encoding='utf-8') as f:
        return json.load(f)

# ==========================================
# 2. 통합 테스트 시나리오
# ==========================================
def test_editor_agent_integration(editor_input):
    if not editor_input:
        pytest.skip("test_editor_data.json not found")

    agent = EditorAgent()
    
    print("\n[STEP 1] node_edit_draft 실행 중 (기사 최종 교정)...")
    state = {
        "llm_mode": "local_only",
        "issue_id": editor_input.get("issue_id"),
        "draft_article": editor_input,
        "total_tokens": {"prompt_tokens": 0, "completion_tokens": 0}
    }
    
    result = agent.node_edit_draft(state)
    
    # 결과 검증
    edited = result.get("edited_article")
    
    assert isinstance(edited, dict)
    
    # 필수 필드 체크 (짧게 출력)
    required = {"issue_id", "title", "description", "background", "core_contentions", "conflict_summary", "media_views", "article_body"}
    actual = set(edited.keys())
    missing = required - actual
    
    if missing:
        pytest.fail(f"MISSING_FIELDS: {list(missing)}")

    assert edited.get("issue_id") == editor_input.get("issue_id")
    print(f"\n[SUCCESS] Title: {edited.get('title')}")

if __name__ == "__main__":
    pytest.main([__file__, "-s"])
