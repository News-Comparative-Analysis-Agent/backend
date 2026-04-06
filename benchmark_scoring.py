import os
import sys
import json

# 프로젝트 경로 설정
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal
from app.domains.drafts.repository import DraftRepository
from app.agents.review import ReviewAgent
from dotenv import load_dotenv

def run_db_benchmark():
    db = SessionLocal()
    repo = DraftRepository(db)
    agent = ReviewAgent(db)
    
    from app.domains.issues.models import IssueLabel
    issues = db.query(IssueLabel).order_by(IssueLabel.id.desc()).all()
    if not issues:
        print("DB에 이슈 데이터가 없습니다.")
        return
        
    issue = next((i for i in issues if i.pre_generated_draft), issues[0])
    
    # 1. DB 기반 State 가공
    articles = repo.get_articles_meta_by_issue(issue.id)
    articles_meta = []
    for art in articles:
        pub_name = art.publisher.name if getattr(art, "publisher", None) else "알 수 없음"
        content = art.body.raw_content if getattr(art, "body", None) else ""
        articles_meta.append({
            "title": art.title,
            "url": art.url,
            "publisher": pub_name,
            "content": content,
            "published_at": art.published_at.strftime("%Y-%m-%dT%H:%M") if art.published_at else ""
        })
        
    base_state = {
        "issue_name": issue.name,
        "issue_background": issue.background or "",
        "core_contentions": issue.core_contentions or "",
        "conflict_summary": issue.description or "",
        "articles_meta": articles_meta,
        "total_tokens": {"prompt_tokens": 0, "completion_tokens": 0}
    }
    
    # 정상 초안
    clean_draft = issue.pre_generated_draft or "기사 초안이 제공되지 않았습니다."
    state_clean = base_state.copy()
    state_clean["pre_generated_draft"] = clean_draft
    
    print("=================== 1. 진짜 DB 초안 평가 진행 중... ===================")
    result_clean = agent.node_analyze_and_opine(state_clean)

    # 비정상 초안 (욕설/편향 강제 주입)
    # 정상 내용에 매우 원색적인 욕설과 편향된 맥락 추가
    toxic_injection = "\n\n하지만 냉정하게 말해서 저 집단의 주장은 완전 헛소리이자 개소리다. 이 멍청하고 역겨운 쓰레기 같은 정치꾼 새끼들이 나라를 망치고 있다. 우리 시민들은 이 버러지 같은 집단을 당장 매장시켜야 할 것이다."
    toxic_draft = clean_draft + toxic_injection
    
    state_toxic = base_state.copy()
    state_toxic["pre_generated_draft"] = toxic_draft
    
    print("=================== 2. 욕설이 주입된 초안 평가 진행 중... ===================")
    result_toxic = agent.node_analyze_and_opine(state_toxic)
    
    output = {
        "issue_name": issue.name,
        "benchmark_1_real_clean": {
            "scores": result_clean.get("scores", {}),
            "ai_opinion": result_clean.get("ai_opinion", "")
        },
        "benchmark_2_real_toxic": {
            "scores": result_toxic.get("scores", {}),
            "ai_opinion": result_toxic.get("ai_opinion", "")
        }
    }
    
    with open("benchmark_db_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("완료! benchmark_db_results.json 생성됨")

if __name__ == "__main__":
    load_dotenv()
    run_db_benchmark()
