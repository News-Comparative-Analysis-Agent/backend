import os
import sys
import json
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app.core.database import SessionLocal
from app.domains.drafts.repository import DraftRepository
from app.agents.review import ReviewAgent

def run_faithfulness_benchmark():
    db = SessionLocal()
    repo = DraftRepository(db)
    agent = ReviewAgent(db)

    print("====================================================================")
    print("원문 충실도 벤치마크: [실제 DB 원문 및 기사 초안 테스트]")
    print("====================================================================\n")

    issues = repo.get_all_issues() if hasattr(repo, 'get_all_issues') else []
    if not issues:
        from app.domains.issues.models import IssueLabel
        issues = db.query(IssueLabel).order_by(IssueLabel.id.desc()).all()
        
    if not issues:
        print("DB에 이슈 데이터가 없습니다.")
        return
        
    issue = next((i for i in issues if i.pre_generated_draft), issues[0])

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

    # 1. 원문 충실도 정상 초안 (DB 원본)
    clean_draft = issue.pre_generated_draft or "기사 초안이 없습니다."
    state_clean = base_state.copy()
    state_clean["pre_generated_draft"] = clean_draft
    
    print(">>> 1. DB 실제 정상 초안 검토 중...")
    result_clean = agent.node_analyze_and_opine(state_clean)

    # 2. 원문 충실도 엉망인 초안 (수치 왜곡, 환각 강제 주입)
    # 왜곡: 극단적 수치 및 존재하지 않는 심각한 사건(환각) 투입
    distorted_injection = "\n\n이 사안과 관련하여 갑자기 관련자 전원이 징역 100년형을 선고받고 전 재산 100조 원을 압수당했다. 당사자들은 기존 입장을 180도 뒤집고 일방적인 항복을 선언했으며, 이 사태로 인해 국가 경제는 순식간에 붕괴하여 코스피 지수가 0으로 추락하고 전국에 계엄령이 선포되었다."
    distorted_draft = clean_draft + distorted_injection

    state_distorted = base_state.copy()
    state_distorted["pre_generated_draft"] = distorted_draft

    print(">>> 2. 수치왜곡 및 허위사실(환각) 떡칠 초안 검토 중...")
    result_distorted = agent.node_analyze_and_opine(state_distorted)

    output = {
        "issue_name": issue.name,
        "benchmark_1_clean": {
            "draft_preview": clean_draft[:200] + "...",
            "scores": result_clean.get("scores", {}),
            "ai_opinion": result_clean.get("ai_opinion", "")
        },
        "benchmark_2_distorted": {
            "draft_preview": distorted_draft[:200] + "... (왜곡 문장 추가됨)",
            "scores": result_distorted.get("scores", {}),
            "ai_opinion": result_distorted.get("ai_opinion", "")
        }
    }

    with open("benchmark_faith_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\n완료! benchmark_faith_results.json 확인")

if __name__ == "__main__":
    load_dotenv()
    run_faithfulness_benchmark()
