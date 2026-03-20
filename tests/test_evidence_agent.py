import os
import json
import pytest
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.core.database import SessionLocal, Base, engine
from app.agents.evidence import EvidenceAgent
from app.scroller.repository import ScrollerRepository
from app.domains.articles.models import Article, ArticleBody, ArticleClaim
from app.domains.issues.models import IssueLabel
from app.domains.publishers.models import Publisher

# ==========================================
# 1. 테스트 환경 설정 (DB)
# ==========================================
@pytest.fixture(scope="module")
def db():
    # 실제 DB 세션 생성
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(scope="module")
def test_data():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(current_dir, 'test_evidence_data.json')
    if not os.path.exists(data_path):
        return None
    with open(data_path, 'r', encoding='utf-8') as f:
        return json.load(f)

# ==========================================
# 3. 통합 테스트 시나리오
# ==========================================
def test_evidence_agent_integration(db: Session, test_data):
    if not test_data:
        pytest.skip("test data (evidence_data.json) not found")

    repo = ScrollerRepository(db)
    agent = EvidenceAgent(db)
    
    # A. 시스템 LLM 모드 확인
    settings = repo.get_system_settings()
    llm_mode = settings.llm_mode
    print(f"\n[INFO] 현재 시스템 LLM 모드: {llm_mode}")

    # B. 테스트용 초기 데이터 생성 (Issue & Articles)
    # 기존 데이터와 충돌을 피하기 위해 임시 데이터 생성
    test_issue = IssueLabel(
        name=f"[TEST] {test_data['issue']['name']}",
        description=test_data['issue']['description'],
        background=test_data['issue']['background']
    )
    db.add(test_issue)
    db.flush()
    
    publisher = repo.get_or_create_publisher("테스트언론사")
    
    created_article_ids = []
    for art in test_data['articles']:
        new_art = Article(
            publisher_id=publisher.id,
            issue_label_id=test_issue.id,
            title=art['title'],
            url=art['url'], # 실제 중복 방지 로직이 있을 수 있으므로 주의
            published_at=datetime.now()
        )
        db.add(new_art)
        db.flush()
        
        body = ArticleBody(article_id=new_art.id, raw_content=art['content'])
        db.add(body)
        created_article_ids.append(new_art.id)
    
    db.commit()
    print(f"[INFO] 테스트 이슈(ID: {test_issue.id}) 및 기사 {len(created_article_ids)}건 생성 완료")

    try:
        # C. EvidenceAgent 실행
        # 초기 상태 설정
        state = {
            "issue_id": test_issue.id,
            "llm_mode": llm_mode, # 실제 DB의 설정을 따름
            "total_tokens": {"prompt_tokens": 0, "completion_tokens": 0}
        }

        # Step 1: node_fetch_articles
        print("[STEP 1] node_fetch_articles 실행 중...")
        fetch_result = agent.node_fetch_articles(state)
        assert len(fetch_result["articles"]) == len(test_data['articles'])
        state.update(fetch_result)

        # Step 2: node_extract_claims (실제 LLM 호출!)
        print(f"[STEP 2] node_extract_claims 실행 중... (Mode: {llm_mode})")
        extract_result = agent.node_extract_claims(state)
        
        # D. 결과 검증
        assert "issue_payload_items" in extract_result
        assert len(extract_result["issue_payload_items"]) > 0
        
        # DB에 저장된 Claim Card 확인
        saved_claims = db.query(ArticleClaim).filter(ArticleClaim.issue_id == test_issue.id).all()
        print(f"[RESULT] DB에 저장된 주장 카드 개수: {len(saved_claims)}")
        assert len(saved_claims) > 0
        
        for i, claim in enumerate(saved_claims):
            print(f"  - Card {i+1}: [{claim.press}] {claim.claim[:50]}...")

        print("[SUCCESS] EvidenceAgent 통합 테스트 완료")

    finally:
        # E. 테스트 데이터 정리 (Cleanup)
        print("[CLEANUP] 테스트 데이터 삭제 중...")
        db.query(ArticleClaim).filter(ArticleClaim.issue_id == test_issue.id).delete()
        db.query(ArticleBody).filter(ArticleBody.article_id.in_(created_article_ids)).delete()
        db.query(Article).filter(Article.id.in_(created_article_ids)).delete()
        db.query(IssueLabel).filter(IssueLabel.id == test_issue.id).delete()
        db.commit()
        print("[CLEANUP] 완료")

if __name__ == "__main__":
    # 스크립트로 직접 실행할 경우를 대비
    pytest.main([__file__, "-s"])
