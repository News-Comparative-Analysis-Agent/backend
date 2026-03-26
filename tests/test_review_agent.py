import os
import sys
import json
import pytest

# 프로젝트 루트를 sys.path에 추가 (도커 환경 대응)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)

# .env 파일 수동 로드
env_path = os.path.join(BASE_DIR, '.env')
if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            if '=' in line and not line.strip().startswith('#'):
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.strip()

from app.agents.review import ReviewAgent
from app.agents.state import ReviewState

def test_review_agent_with_json_data():
    """
    ReviewAgent의 핵심 로직을 tests/test_review_agent.json 데이터를 직접 사용하여 테스트합니다.
    이 테스트는 DB에 의존하지 않습니다.
    """
    # 1. JSON 데이터 로드
    json_path = os.path.join(os.path.dirname(__file__), 'test_review_agent.json')
    if not os.path.exists(json_path):
        pytest.skip(f"테스트 데이터 파일({json_path})을 찾을 수 없습니다.")
    
    with open(json_path, 'r', encoding='utf-8') as f:
        test_data = json.load(f)
    
    print(f"\n🚀 Testing ReviewAgent with JSON Data: {test_data.get('title')}")

    agent = ReviewAgent(db=None) # DB 세션 불필요
    
    # 2. JSON 데이터를 기반으로 ReviewState 구성
    # articles_meta 구성 (media_views 데이터를 변환)
    articles_meta = []
    for view in test_data.get("media_views", []):
        articles_meta.append({
            "title": view.get("claim", "테스트 기사 제목"),
            "url": view.get("url", ""),
            "publisher": view.get("press", "알 수 없음"),
            "published_at": ""
        })

    state: ReviewState = {
        "llm_mode": "local_priority",
        "issue_id": test_data.get("issue_id", 1),
        "issue_name": test_data.get("title", ""),
        "issue_description": test_data.get("description", ""),
        "issue_background": test_data.get("background", ""),
        "core_contentions": test_data.get("core_contentions", ""), # JSON에 없으면 기본값
        "conflict_summary": test_data.get("conflict_summary", ""),
        "pre_generated_draft": test_data.get("article_body", ""),
        "articles_meta": articles_meta,
        "messages": [],
        "total_tokens": {"prompt_tokens": 0, "completion_tokens": 0}
    }

    # Node 1: Fetch (생략 - JSON 데이터로 이미 채워짐)
    print("Step 1: Skipping DB Fetch (using JSON data)...")

    # Node 3: Analyze and Opine (가이드라인 검증 및 종합 의견)
    print("Step 3: Analyzing guidelines and generating AI opinion...")
    # Gemini API 키 설정 확인
    if not os.getenv("GOOGLE_API_KEY"):
        print("⚠️ Warning: GOOGLE_API_KEY not found. LLM call will use local 7B if configured.")

    opine_res = agent.node_analyze_and_opine(state)
    state.update(opine_res)
    
    assert "guideline_checks" in state
    assert len(state["guideline_checks"]) > 0
    assert state["ai_opinion"] != ""
    
    print("\n=== [Review Result] ===")
    for check in state["guideline_checks"]:
        status = "✅ PASS" if check["passed"] else "❌ FAIL"
        print(f"[{check['label']}] {status} - {check['detail']}")
    
    print(f"\n[AI Opinion]\n{state['ai_opinion']}")
    print(f"\n[Total Tokens] {state['total_tokens']}")
    print("========================")

if __name__ == "__main__":
    # 직접 실행 시 pytest 구동
    pytest.main([__file__, "-s"])
