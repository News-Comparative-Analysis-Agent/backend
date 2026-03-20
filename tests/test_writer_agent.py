import os
import json
import pytest
from app.agents.writer import WriterAgent

# ==========================================
# 1. 데이터 로드 유틸리티
# ==========================================
@pytest.fixture(scope="module")
def writer_input():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(current_dir, 'test_writer_data.json')
    if not os.path.exists(data_path):
        return {}
    with open(data_path, 'r', encoding='utf-8') as f:
        return json.load(f)

# ==========================================
# 2. 통합 테스트 시나리오
# ==========================================
def test_writer_agent_integration(writer_input):
    if not writer_input:
        pytest.skip("test_writer_data.json not found")

    agent = WriterAgent()
    
    print("\n[STEP 1] node_write_draft 실행 중 (비평 기사 본문 작성)...")
    state = {
        "llm_mode": "gemini_only",
        **writer_input,
        "total_tokens": {"prompt_tokens": 0, "completion_tokens": 0}
    }
    
    result = agent.node_write_draft(state)
    
    # 결과 검증
    print("\n[RESULT] 생성된 최종 비평 데이터:")
    draft = result.get("draft_article")
    
    assert isinstance(draft, dict)
    print(f"  - 제목: {draft.get('title')}")
    print(f"  - 쟁점 요약: {draft.get('core_contentions')}")
    print(f"  - 본문 길이: {len(draft.get('article_body', ''))}자")
    
    # 필수 필드 체크
    required_fields = ["issue_id", "title", "description", "background", "core_contentions", "conflict_summary", "media_views", "article_body"]
    for field in required_fields:
        assert field in draft, f"Missing field: {field}"
        assert draft[field] is not None, f"Field {field} is None"

    assert len(draft.get("article_body", "")) > 100
    assert len(draft.get("media_views", [])) == len(writer_input.get("media_views", []))

    print("\n[SUCCESS] WriterAgent 통합 테스트 완료")

if __name__ == "__main__":
    pytest.main([__file__, "-s"])
