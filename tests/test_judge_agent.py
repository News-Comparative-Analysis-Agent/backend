import os
import json
import pytest
from app.agents.judge import JudgeAgent

# ==========================================
# 1. 데이터 로드 유틸리티
# ==========================================
@pytest.fixture(scope="module")
def judge_input():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(current_dir, 'test_judge_data.json')
    if not os.path.exists(data_path):
        return {}
    with open(data_path, 'r', encoding='utf-8') as f:
        return json.load(f)

# ==========================================
# 2. 통합 테스트 시나리오
# ==========================================
def test_judge_agent_integration(judge_input):
    if not judge_input:
        pytest.skip("test_judge_data.json not found")

    agent = JudgeAgent()
    
    print("\n[STEP 1] node_evaluate_draft 실행 중 (최종 품질 검수)...")
    
    # judge_input의 모든 필드를 state로 언패킹하여 전달
    state = {
        "llm_mode": "gemini_only",
        "retry_count": 0,
        "total_tokens": {"prompt_tokens": 0, "completion_tokens": 0},
        "messages": [],
        **judge_input
    }
    
    result = agent.node_evaluate_draft(state)
    
    # 결과 검증
    status = result.get("judge_status")
    feedback = result.get("judge_feedback")
    
    print(f"\n[RESULT] Status: {status}")
    print(f"[RESULT] Feedback: {feedback}")
    
    # 기본 필드 존재 여부 확인
    assert status in ["PASS", "FAIL_WRITER", "FAIL_EDITOR"]
    assert feedback is not None
    
    print("\n[SUCCESS] JudgeAgent 검증 로직 정상 동작 확인")

if __name__ == "__main__":
    pytest.main([__file__, "-s"])
