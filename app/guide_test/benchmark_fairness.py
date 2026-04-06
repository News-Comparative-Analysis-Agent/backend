import os
import sys
import json
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app.core.database import SessionLocal
from app.domains.drafts.repository import DraftRepository
from app.agents.review import ReviewAgent

def run_fairness_benchmark():
    db = SessionLocal()
    repo = DraftRepository(db)
    agent = ReviewAgent(db)

    print("====================================================================")
    print("⚖️ 공정성(Fairness) 벤치마크: [실제 DB 원문 기반 관점 균형 & 감정 표현 테스트]")
    print("====================================================================\n")

    issues = repo.get_all_issues() if hasattr(repo, 'get_all_issues') else []
    if not issues:
        from app.domains.issues.models import IssueLabel
        issues = db.query(IssueLabel).order_by(IssueLabel.id.desc()).all()
        
    if not issues:
        print("DB에 이슈 데이터가 없습니다.")
        return
        
    # 초안이 있는 가장 최근 이슈 가져오기
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
        })

    base_state = {
        "issue_name": issue.name,
        "issue_background": issue.background or "",
        "core_contentions": issue.core_contentions or "",
        "conflict_summary": issue.description or "",
        "articles_meta": articles_meta,
        "total_tokens": {"prompt_tokens": 0, "completion_tokens": 0}
    }

    # 1. 공정성 정상 초안 (DB 원본)
    # 여러 관점이 들어있고, 감정적 단어가 없는 객관적 상태 (예상: 4점)
    clean_draft = issue.pre_generated_draft or "기사 초안이 없습니다."
    state_clean = base_state.copy()
    state_clean["pre_generated_draft"] = clean_draft
    
    print(">>> 1. DB 실제 [정상 초안] 평가 중... (예상: 관점 2개 이상, 감정 단어 0%)")
    result_clean = agent.node_analyze_and_opine(state_clean)

    # 2. 하나의 관점만 남기고, 매우 감정적인 단어로 편향성을 주입한 초안
    # 원문 내의 단어들을 극단적인 감정 단어로 대량 치환하여 감정 단어 비율 5% 초과 유도
    # 또한 반대 입장에 대한 서술을 깎아내려서 관점을 편향되게 조작
    biased_injection = """
\n\n결론적으로 우리 측의 주장이 구국의 결단이자 소름 돋게 위대하고 경이로우며 압도적으로 성공적인 행보임이 참으로 명백하다. 
저 반대측 놈들은 충격적이고 끔찍하며 파멸적이고 처참한 최악의 무능함을 보여줌으로써 모두를 경악하게 만들고 있다! 
정말이지 너무나도 아름답고 찬란한 이 결정은 역사상 가장 환상적이고 기적적인 성과로 영원하고 눈부시게 빛날 것이다. 
반면 저들의 더럽고 심각하고 기괴하며 참담한 작태는 분노를 유발하는 극악무도하고 혐오스러운 비극일 뿐이다! 
위대하고도 전설적인 이 승리를 우리는 열렬히 찬송하고 찬양해야만 한다!!
    """ * 3  # 길이를 늘려서 비율을 확 올림
    
    # DB 원문(정상)을 가져와서 강제로 감정적 단어로 변조 (원문 훼손)
    biased_draft = clean_draft.replace("주장", "억지 헛소리").replace("입장", "구차한 변명").replace("법적 대응", "무자비한 정치보복").replace("의혹", "추악한 범죄 행위")
    biased_draft += biased_injection

    state_biased = base_state.copy()
    state_biased["pre_generated_draft"] = biased_draft

    print(">>> 2. 관점 편향 및 감정단어(충격적, 위대한 등) 떡칠 초안 평가 중... (예상: 공정성 대폭 감점)")
    result_biased = agent.node_analyze_and_opine(state_biased)

    output = {
        "issue_name": issue.name,
        "benchmark_1_fair_clean": {
            "draft_preview": clean_draft[:100] + "...",
            "scores": result_clean.get("scores", {}),
            "ai_opinion": result_clean.get("ai_opinion", "")
        },
        "benchmark_2_unfair_biased": {
            "draft_preview": biased_draft[-150:] + "...",
            "scores": result_biased.get("scores", {}),
            "ai_opinion": result_biased.get("ai_opinion", "")
        }
    }

    with open("benchmark_fairness_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\n완료! benchmark_fairness_results.json 확인")

if __name__ == "__main__":
    load_dotenv()
    run_fairness_benchmark()
