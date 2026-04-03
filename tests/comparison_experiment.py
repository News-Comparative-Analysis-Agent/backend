import os
import sys
import json
import time
from typing import List, Dict, Any

# 프로젝트 루트 디렉토리를 sys.path에 추가
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.core.database import SessionLocal
from app.agents.utils import call_gemini, call_llm, get_local_model_name
from app.scroller.graph import create_comparison_graph
from sqlalchemy.orm import Session
from sqlalchemy import delete
from app.core.logger import logger, log_llm_event
from app.domains.articles.models import Article, ArticleBody
from app.domains.publishers.models import Publisher
from app.domains.issues.models import IssueLabel
from datetime import datetime

def sync_test_data(db: Session, test_articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """run_local_full_test.py의 동기화 로직을 이식하여 기사 데이터를 DB에 준비합니다."""
    logger.info("💾 [Sync] 테스트 기사를 DB에 동기화 중...")
    formatted_articles = []
    
    # 기존 데이터 초기화 (선택적: 테스트 이슈들만 정리)
    # db.execute(delete(ArticleBody))
    # db.execute(delete(Article))
    # db.commit()

    for item in test_articles:
        # 언론사 확인 및 생성
        publisher = db.query(Publisher).filter(Publisher.name == item["press"]).first()
        if not publisher:
            publisher = Publisher(name=item["press"], type="etc")
            db.add(publisher)
            db.flush()
        
        # 기사 생성 (Get or Create 패턴)
        existing_article = db.query(Article).filter(Article.url == item["url"]).first()
        
        if existing_article:
            new_article = existing_article
            new_article.title = item["title"]
            new_article.issue_label_id = None # 초기화
            db.flush()
        else:
            new_article = Article(
                title=item["title"],
                url=item["url"],
                publisher_id=publisher.id,
                published_at=datetime.now(),
                issue_label_id=None
            )
            db.add(new_article)
            db.flush()
        
        # 본문 저장 (기존 본문 삭제 후 새로 추가하거나 업데이트)
        db.execute(delete(ArticleBody).where(ArticleBody.article_id == new_article.id))
        db.flush()
        
        new_body = ArticleBody(article_id=new_article.id, raw_content=item.get("content", item["title"]))
        db.add(new_body)
        db.flush()

        formatted_articles.append({
            "article_id": new_article.id,
            "title": item["title"],
            "content": item.get("content", item["title"]),
            "press": item["press"]
        })
    
    db.commit()
    logger.info(f"✅ {len(formatted_articles)}개의 기사가 DB와 연동되었습니다.")
    return formatted_articles

def run_agentic_flow(db: Session, formatted_articles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """멀티에이전트 그래프를 실행하고 최종 결과물을 추출합니다."""
    logger.info("🚀 [Agentic] 멀티에이전트(LangGraph) 파이프라인 가동...")
    start_time = time.time()
    
    app = create_comparison_graph(db)
    initial_state = {
        "llm_mode": "local_only",
        "issue_id": None,
        "all_issue_ids": [],
        "raw_articles": [],
        "unclustered_articles": formatted_articles, 
        "clustered_topics": [],
        "total_tokens": {"prompt_tokens": 0, "completion_tokens": 0},
        "messages": [],
        "error": ""
    }
    
    config = {"configurable": {"thread_id": "comparison_test_run"}}
    final_state = app.invoke(initial_state, config=config)
    duration = time.time() - start_time
    
    # 생성된 첫 번째 이슈의 초안을 가져옵니다.
    issue_ids = final_state.get("all_issue_ids", [])
    agent_draft = {}
    
    if issue_ids:
        issue = db.query(IssueLabel).filter(IssueLabel.id == issue_ids[0]).first()
        if issue and issue.pre_generated_draft:
            try:
                agent_draft = json.loads(issue.pre_generated_draft)
            except:
                agent_draft = {"article_body": issue.pre_generated_draft}
                
    return {
        "draft": agent_draft,
        "tokens": final_state.get("total_tokens", {}),
        "duration": duration,
        "issue_id": issue_ids[0] if issue_ids else None
    }

def run_baseline_flow(test_articles: List[Dict[str, Any]], llm_mode: str = "local_only") -> Dict[str, Any]:
    """설정된 llm_mode에 따라 종합 비평 기사를 작성합니다."""
    logger.info(f"🧪 [Baseline] 단일 시도(Single-Pass, 모드: {llm_mode}) 시작...")
    start_time = time.time()
    
    # 기사 데이터 텍스트화
    articles_context = ""
    for idx, art in enumerate(test_articles, 1):
        articles_context += f"기사 {idx} [{art['press']}]: {art['title']}\n본문: {art.get('content', '')}\n\n"

    prompt = f"""
당신은 대한민국 최고의 권위를 가진 **수석 논설위원**입니다. 
제공된 여러 언론사의 원본 기사들을 '심층 분석'하여, 사안에 대한 각 매체의 프레임(Frame) 차이와 논리적 대립을 날카롭게 포착하는 **[통합 비평 칼럼]**을 작성하십시오.

[원본 기사 데이터]
{articles_context}

[집필 및 품질 지침 🖋️]
1. **철저한 팩트 준수 (Anti-Hallucination)**: 반드시 제공된 기사 데이터 내의 사실만 사용하십시오. **절대 존재하지 않는 기사 제목, 통계, 인용구를 지어내거나 날조하지 마십시오.** 
2. **매체별 실명 인용**: 분석 시 반드시 해당 언론사의 이름을 명시하십시오. (예: "A 언론은 ~라고 보도한 반면, B 언론은 ~에 주목했다")
3. **입체적 프레임 분석**: 단순히 사실을 요약하지 마십시오. 각 언론사가 왜 그런 시각을 가지는지, 그 이면에 깔린 핵심 의도와 프레임을 날카롭게 대조하십시오.
4. **논리적 서사 구조**:
   - [도입]: 사안의 발단과 현재 선거판/사회에 던지는 본질적인 질문
   - [본문]: 대립하는 언론사들의 시각을 그룹화하여 입체적으로 대조 및 분석
   - [결론]: 이 논쟁이 독자에게 주는 시사점과 향후 전망
5. **품격 있는 문체**: 정중하고 지적이며, 객관성을 유지하는 논설위원 특유의 무게감 있는 문체를 사용하십시오.
6. **형식**: 제목을 반드시 포함하고, 신문 지면에 즉시 실릴 수 있는 '완성된 기사 텍스트' 그 자체만 한국어로 출력하십시오. (JSON/마크다운 코드 블록 금지)
"""
    # 통합 호출 함수 활용 (llm_mode에 따른 라우팅 자동 처리)
    from app.agents.utils import call_llm_text
    
    # dummy state 생성하여 모드 전달
    dummy_state = {"llm_mode": llm_mode}
    
    result_text, tokens = call_llm_text(prompt, "7B", dummy_state)
    duration = time.time() - start_time
    
    # 로깅 추가: 응답 본문 및 토큰 사용량
    node_name = "Baseline-Local" if "local" in llm_mode else "Baseline-Gemini"
    log_llm_event(node_name, f"Response received from {llm_mode}", details=result_text, token_info=tokens)
    logger.info(f"✅ [Baseline] 기사 작성 완료 (소요 시간: {duration:.2f}초)")
    
    return {
        "draft": {"article_body": result_text}, # 평가 호환성을 위해 dict 감쌈
        "tokens": tokens,
        "duration": duration
    }

def run_evaluation(agent_draft: Dict[str, Any], baseline_draft: Dict[str, Any], raw_articles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """심판 LLM(Gemini 2.0 Flash)을 통해 원본 데이터와 결과물을 정밀 대조 채점합니다."""
    logger.info("⚖️ [Judge] 원본 데이터 대조 및 전문 평가 중...")
    
    # 원본 데이터 요약 (제목 및 본문 요약)
    ground_truth = ""
    for i, art in enumerate(raw_articles):
        ground_truth += f"--- [원본 기사 {i+1}] ---\n제목: {art.get('title')}\n본문: {art.get('content', '')[:1000]}...\n\n"

    ma_text = agent_draft.get("article_body", "")
    ma_views = json.dumps(agent_draft.get("media_views", []), ensure_ascii=False)
    
    sp_text = baseline_draft.get("article_body", "")
    # Baseline은 media_views가 없을 수 있으므로 빈 리스트 처리
    sp_views = json.dumps(baseline_draft.get("media_views", []), ensure_ascii=False)

    prompt = f"""
다음은 동일한 원본 기사들을 바탕으로 작성된 두 가지 '언론사별 시각 분석 비평 기사'입니다.
제시된 [원본 데이터(Ground Truth)]와 대조하여 각 기사의 정확성과 분석의 깊이를 평가하세요.

[원본 데이터 (Ground Truth)]
{ground_truth}

[후보 A: Multi-Agent 시스템 결과]
- 본문: {ma_text}
- 분석 데이터(Media Views): {ma_views}

[후보 B: Single-Pass (단일 프롬프트) 결과]
- 본문: {sp_text}

[평가 지표 (1~10점)]
1. Accuracy: 원본 기사의 팩트로부터 이탈하거나 없는 사실을 지어내지(Hallucination) 않았는가?
2. Frame: 각 언론사가 강조한 시각 차이와 논조를 정확하고 예리하게 포착했는가?
3. Logic: 비평 기사로서 문장 간 연결이 자연스럽고 논리적 흐름이 탄탄한가?
4. Overall: 독자에게 통찰을 주는 최종 결과물로서의 완성도가 어떠한가?

[평가 지침]
- 팩트 왜곡이나 존재하지 않는 날짜/숫자가 발견될 경우 Accuracy 항목에서 크게 감점하십시오.
- 단순히 매체를 나열한 것보다, 주제 중심으로 시각을 통합한 기사에 가점을 줍니다.

[응답 형식]
JSON 형식으로 점수와 총평을 반환하세요.
{{
  "scores": {{
    "multi_agent": {{ "accuracy": 0, "frame": 0, "logic": 0, "overall": 0 }},
    "single_pass": {{ "accuracy": 0, "frame": 0, "logic": 0, "overall": 0 }}
  }},
  "verdict": "원본 데이터 대조 기반의 장단점 비교 및 구체적인 근거 제시",
  "winner": "Multi-Agent" 또는 "Single-Pass"
}}
"""
    result, _ = call_gemini(prompt)
    if not isinstance(result, dict):
        # 파싱 실패 대비
        import re
        try:
             json_str = re.search(r'\{.*\}', result, re.DOTALL).group()
             result = json.loads(json_str)
        except:
             result = {"winner": "N/A", "verdict": "Failed to parse judge result.", "scores": {"multi_agent": {}, "single_pass": {}}}
    return result

def main():
    logger.info("🏁 [통합 실험] Multi-Agent vs. Single-Pass (Gemini Only)")
    
    # 1. 데이터 로드
    json_path = os.path.join(BASE_DIR, "tests", "full_test_data.json")
    if not os.path.exists(json_path):
        logger.error(f"❌ 데이터 파일을 찾을 수 없습니다: {json_path}")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        test_articles = json.load(f)

    db = SessionLocal()
    LLM_MODE = "local_only" # 실험 모드 (local_only, gemini_only, local_priority 등)
    
    # 실제 모델명 조회
    actual_model_name = get_local_model_name() if LLM_MODE == "local_only" else LLM_MODE.upper()
    logger.info(f"🤖 [Benchmark] 현재 참여 모델: {actual_model_name}")

    try:
        # Step A: DB 동기화 (run_local_full_test 로직)
        formatted_articles = sync_test_data(db, test_articles)
        
        # Step B: Agentic Flow 실행 (Full Graph)
        agent_res = run_agentic_flow(db, formatted_articles)
        
        # Step C: Baseline Flow 실행 (One Shot)
        # Baseline도 동일한 모델을 사용하도록 llm_mode 전달
        base_res = run_baseline_flow(test_articles, llm_mode=LLM_MODE)
        
        # Step D: Judge Evaluation (Grounded Assessment)
        judge_res = run_evaluation(agent_res["draft"], base_res["draft"], test_articles)
        
        # Step E: 리포트 생성
        report_md = f"""# 📊 통합 실험 결과 리포트 (Agentic vs. Baseline)
        - **실험 일시**: {time.strftime('%Y-%m-%d %H:%M:%S')}
        - **사용 모델**: {actual_model_name}
        - **수행 이슈 ID**: {agent_res.get('issue_id', 'N/A')}

        ## 1. 📊 성능 및 총 소요량
        | 지표 | Multi-Agent (Agentic) | Single-Pass (Baseline) |
        | :--- | :--- | :--- |
        | **소요 시간** | {agent_res['duration']:.2f}s | {base_res['duration']:.2f}s |
        | **프롬프트 토큰** | {agent_res['tokens'].get('prompt_tokens', 0):,} | {base_res['tokens'].get('prompt_tokens', 0):,} |
        | **완성 토큰** | {agent_res['tokens'].get('completion_tokens', 0):,} | {base_res['tokens'].get('completion_tokens', 0):,} |

        ## 2. ⭐ 심판 채점 결과 (Judge Evaluation)
        | 평가 항목 | Multi-Agent | Single-Pass |
        | :--- | :--- | :--- |
        """
        ma_s = judge_res.get("scores", {}).get("multi_agent", {})
        sp_s = judge_res.get("scores", {}).get("single_pass", {})
        
        for k in ["frame", "logic", "accuracy", "overall"]:
            report_md += f"| {k.capitalize()} | {ma_s.get(k, 0)} | {sp_s.get(k, 0)} |\n"
        
        report_md += f"""
        ---
        ### 🏆 최종 승자: **{judge_res.get('winner', 'N/A')}**
        ### 📝 심판 총평
        {judge_res.get('verdict', '')}

        ---
        ## 3. 📝 생성 결과물 샘플 (Article Body)
        ### [Multi-Agent (Agentic)]
        {agent_res['draft'].get('article_body', '생성 실패')}

        ### [Single-Pass (Baseline)]
        {base_res['draft'].get('article_body', '생성 실패')}
        """
        # 결과 저장 폴더 생성
        results_dir = os.path.join(BASE_DIR, "tests", "results")
        if not os.path.exists(results_dir):
            os.makedirs(results_dir)
            
        # 타임스탬프 및 모델명 기반 개별 리포트 저장 (로컬 모델 대항전용)
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        safe_model_name = actual_model_name.replace("/", "_").replace(" ", "_")
        history_report_path = os.path.join(results_dir, f"report_{timestamp}_{safe_model_name}.md")
        with open(history_report_path, "w", encoding="utf-8") as rf:
            rf.write(report_md)
            
        # 최신 리포트 보존 (기존 경로)
        latest_report_path = os.path.join(BASE_DIR, "tests", "comparison_report.md")
        with open(latest_report_path, "w", encoding="utf-8") as rf:
            rf.write(report_md)
        
        logger.success(f"✅ 통합 실험 완료!")
        logger.success(f"   └─ 고유 리포트: {history_report_path}")
        logger.success(f"   └─ 최신 리포트: {latest_report_path}")

    except Exception as e:
        logger.critical(f"💥 실험 실행 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()
