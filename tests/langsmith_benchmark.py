import os
import json
import asyncio
import time
from typing import List, Dict, Any
from langsmith import Client, evaluate
from dotenv import load_dotenv

load_dotenv()

from app.scroller.graph import create_comparison_graph
from app.agents.utils import call_llm, call_gemini
from app.core.database import SessionLocal
from app.domains.articles.models import Article
from app.domains.publishers.models import Publisher
from sqlalchemy.orm import Session

def sync_test_data(db: Session, test_articles: List[Dict[str, Any]]):
    for item in test_articles:
        publisher = db.query(Publisher).filter(Publisher.name == item["press"]).first()
        if not publisher:
            publisher = Publisher(name=item["press"], type="etc")
            db.add(publisher)
            db.flush()
        existing_article = db.query(Article).filter(Article.url == item["url"]).first()
        if not existing_article:
            new_article = Article(
                title=item["title"],
                url=item["url"],
                publisher_id=publisher.id,
                issue_label_id=None
            )
            db.add(new_article)
    db.commit()

async def multi_agent_target(inputs: dict) -> dict:
    from app.domains.issues.models import IssueLabel
    db = SessionLocal()
    llm_mode = inputs.get("llm_mode", "local_only")
    try:
        app_graph = create_comparison_graph(db)
        
        # article_id 확보 로직
        formatted_articles = []
        for art in inputs.get("articles", []):
            db_art = db.query(Article).filter(Article.url == art["url"]).first()
            formatted_articles.append({
                "article_id": db_art.id if db_art else None,
                "title": art["title"],
                "content": art.get("content", art["title"]),
                "press": art["press"]
            })
        
        initial_state = {
            "llm_mode": llm_mode,
            "issue_id": None,
            "all_issue_ids": [],
            "raw_articles": [],
            "unclustered_articles": formatted_articles, 
            "clustered_topics": [],
            "total_tokens": {"prompt_tokens": 0, "completion_tokens": 0},
            "messages": [],
            "error": ""
        }
        
        config = {"configurable": {"thread_id": "langsmith_test"}}
        final_state = app_graph.invoke(initial_state, config=config)
        
        issue_ids = final_state.get("all_issue_ids", [])
        agent_draft = {}
        
        if issue_ids:
            issue = db.query(IssueLabel).filter(IssueLabel.id == issue_ids[0]).first()
            if issue and issue.pre_generated_draft:
                try:
                    agent_draft = json.loads(issue.pre_generated_draft)
                except:
                    agent_draft = {"article_body": issue.pre_generated_draft}
                    
        body = agent_draft.get("article_body", "") if isinstance(agent_draft, dict) else str(agent_draft)
        return {
            "output": body,
            "title": agent_draft.get("title", "") if isinstance(agent_draft, dict) else "",
            "description": agent_draft.get("description", "") if isinstance(agent_draft, dict) else "",
            "background": agent_draft.get("background", "") if isinstance(agent_draft, dict) else "",
            "core_contentions": agent_draft.get("core_contentions", "") if isinstance(agent_draft, dict) else "",
            "conflict_summary": agent_draft.get("conflict_summary", "") if isinstance(agent_draft, dict) else "",
            "media_views": agent_draft.get("media_views", []) if isinstance(agent_draft, dict) else [],
            "tokens": final_state.get("total_tokens", {})
        }
    finally:
        db.close()

async def single_pass_target(inputs: dict) -> dict:
    articles = inputs.get("articles", [])
    llm_mode = inputs.get("llm_mode", "local_only")
    
    articles_context = ""
    for idx, art in enumerate(articles, 1):
        articles_context += f"기사 {idx} [{art['press']}]: {art['title']}\n본문: {art.get('content', '')}\n\n"

    prompt = f"""
당신은 대한민국 최고의 권위를 가진 **수석 논설위원**입니다. 
제공된 여러 언론사의 원본 기사들을 '심층 분석'하여, 사안에 대한 각 매체의 프레임(Frame) 차이와 논리적 대립을 날카롭게 포착하는 **[통합 비평 칼럼]**을 작성하십시오.

[원본 기사 데이터]
{articles_context}

[집필 및 품질 지침 🖋️]
1. **철저한 팩트 준수 (Anti-Hallucination)**: 반드시 제공된 기사 데이터 내의 사실만 사용하십시오. 절대 존재하지 않는 사실을 날조하지 마십시오. 
2. **매체별 실명 인용**: 분석 시 반드시 해당 언론사의 이름을 명시하십시오.
3. **입체적 프레임 분석**: 각 언론사의 핵심 의도와 프레임을 날카롭게 대조하십시오.
4. **논리적 서사 구조**: [도입], [본문], [결론] 순으로 작성하십시오.
5. **형식**: 반드시 아래 제공된 출력 JSON 스키마를 엄격히 준수하십시오.

[출력 JSON 스키마]
{{
  "issue_id": 0,
  "title": "통찰력 있는 기사 제목",
  "description": "배경과 갈등을 한눈에 보여주는 심층 요약",
  "background": "구조적 배경 설명",
  "core_contentions": "대립하는 핵심 가치",
  "conflict_summary": "매체 간의 시각 차이를 '대조'와 '대립'의 관점에서 요약",
  "media_views": [
    {{
      "press": "언론사명",
      "claim": "핵심 주장",
      "evidence": "인용된 근거(수정 금지)",
      "url": "기사 URL(수정 금지)",
      "narrative": "해당 매체의 프레임 분석"
    }}
  ],
  "article_body": "원본의 풍부한 맥락을 반영하여 재조직된, 매끄러운 최종 통합 비평 기사 본문"
}}

※ 주의: 반드시 위 [출력 JSON 스키마]의 모든 필드(title, description, article_body 등)를 포함한 하나의 JSON 객체만 반환하세요.
"""
    start_time = time.time()
    result_data, tokens = call_llm(prompt, "local", {"llm_mode": llm_mode})
    duration = time.time() - start_time
    
    if isinstance(result_data, dict):
        result_text = result_data.get("article_body", str(result_data))
        media_views = result_data.get("media_views", [])
        title = result_data.get("title", "")
        description = result_data.get("description", "")
        background = result_data.get("background", "")
        core_contentions = result_data.get("core_contentions", "")
        conflict_summary = result_data.get("conflict_summary", "")
    else:
        result_text = str(result_data)
        media_views = []
        title = ""
        description = ""
        background = ""
        core_contentions = ""
        conflict_summary = ""

    return {
        "output": result_text,
        "title": title,
        "description": description,
        "background": background,
        "core_contentions": core_contentions,
        "conflict_summary": conflict_summary,
        "media_views": media_views,
        "duration": duration,
        "tokens": {"prompt_tokens": tokens.get("prompt_tokens", 0), "completion_tokens": tokens.get("completion_tokens", 0)}
    }

def precision_evaluator(run, example) -> dict:
    """Gemini 2.0을 랭스미스 심판으로 사용하여 0.0~10.0의 소수점 점수를 산출합니다."""
    # 원본 기사 데이터 확보
    articles = example.inputs.get("articles", [])
    articles_context = ""
    for idx, art in enumerate(articles, 1):
        articles_context += f"--- [원본 기사 {idx} - {art.get('press', '알수없음')}] ---\n{art.get('title', '')}\n본문: {art.get('content', '')[:1000]}...\n\n"
        
    ground_truth = example.outputs.get("full_ground_truth", "")
    output_body = run.outputs.get("output", "")
    media_views = run.outputs.get("media_views", [])
    
    import json
    prediction_payload = {
        "title": run.outputs.get("title", ""),
        "description": run.outputs.get("description", ""),
        "background": run.outputs.get("background", ""),
        "core_contentions": run.outputs.get("core_contentions", ""),
        "conflict_summary": run.outputs.get("conflict_summary", ""),
        "media_views": media_views,
        "article_body": output_body
    }
    prediction_str = json.dumps(prediction_payload, ensure_ascii=False, indent=2)
    
    # 조기 방어: 결과물이 도출되지 않았을 경우, 불필요한 LLM 호출 없이 0점으로 채점
    if not output_body or len(output_body.strip()) < 10:
        return [
            {"key": "avg_precision_score", "score": 0.0, "comment": "[치명적 오류] 기사 생성 실패"},
            {"key": "accuracy", "score": 0.0},
            {"key": "title_score", "score": 0.0},
            {"key": "description_score", "score": 0.0},
            {"key": "background_score", "score": 0.0},
            {"key": "contentions_score", "score": 0.0},
            {"key": "conflict_score", "score": 0.0},
            {"key": "extraction_score", "score": 0.0},
            {"key": "body_score", "score": 0.0}
        ]
    
    prompt = f"""
    당신은 랭스미스 평가관(Judge)입니다. [원본 뉴스 데이터]와 시스템이 구조화한 [평가 대상 결과물]을 비교하여 0.0점부터 10.0점까지 소수점 첫째 자리(예: 8.7, 9.2)로 깐깐하게 채점하세요.

    [원본 뉴스 데이터]
    {articles_context}
    
    [모범 예시 (Ground Truth - 참고용)]
    {ground_truth}
    
    [평가 대상 결과물]
    {prediction_str}
    
    [평가 지표 (0.0~10.0)]
    1. accuracy: 모든 데이터가 원본 기사로부터 이탈하거나 팩트 왜곡(할루시네이션)이 없는가?
    2. title_score: 기사의 통찰력이 담긴 압축적이고 매력적인 제목인가?
    3. description_score: 사안의 배경과 갈등의 요지를 한눈에 파악할 수 있게 심층 요약되었는가?
    4. background_score: 사건 이면의 구조적 배경이 풍부하게 잘 서술되었는가?
    5. contentions_score: 양 진영 간에 대립하는 핵심 가치 기준이 정확히 도출되었는가?
    6. conflict_score: 매체 간의 논조 차이가 '대조'와 '대립'의 관점에서 적확하게 요약되었는가?
    7. extraction_score: 'media_views' 내에 각 매체의 주장(claim)과 근거가 원본에서 올바르게 추출되었는가?
    8. body_score: 본문(article_body) 문장 간 논리 전개가 매끄럽고 전반적인 완성도가 뛰어난가?
    
    오직 JSON 형식으로만 응답하세요:
    {{
      "accuracy": "[0.0 ~ 10.0 사이의 소수점]",
      "title_score": "[0.0 ~ 10.0 사이의 소수점]",
      "description_score": "[0.0 ~ 10.0 사이의 소수점]",
      "background_score": "[0.0 ~ 10.0 사이의 소수점]",
      "contentions_score": "[0.0 ~ 10.0 사이의 소수점]",
      "conflict_score": "[0.0 ~ 10.0 사이의 소수점]",
      "extraction_score": "[0.0 ~ 10.0 사이의 소수점]",
      "body_score": "[0.0 ~ 10.0 사이의 소수점]",
      "verdict": "각 지표 평가 결과에 대한 상세한 심사평 내용"
    }}
    """
    judge_res, _ = call_gemini(prompt)
    if not isinstance(judge_res, dict):
        import re
        try:
             json_str = re.search(r'\{.*\}', judge_res, re.DOTALL).group()
             judge_res = json.loads(json_str)
        except:
             judge_res = {"verdict": "Parsing error", "accuracy": 0.0, "title_score": 0.0, "description_score": 0.0, "background_score": 0.0, "contentions_score": 0.0, "conflict_score": 0.0, "extraction_score": 0.0, "body_score": 0.0}
             
    avg_score = (
        float(judge_res.get("accuracy",0)) +
        float(judge_res.get("title_score",0)) +
        float(judge_res.get("description_score",0)) +
        float(judge_res.get("background_score",0)) +
        float(judge_res.get("contentions_score",0)) +
        float(judge_res.get("conflict_score",0)) +
        float(judge_res.get("extraction_score",0)) +
        float(judge_res.get("body_score",0))
    ) / 8.0
    return [
        {"key": "avg_precision_score", "score": avg_score / 10.0, "comment": judge_res.get("verdict", "")},
        {"key": "accuracy", "score": float(judge_res.get("accuracy",0)) / 10.0},
        {"key": "title_score", "score": float(judge_res.get("title_score",0)) / 10.0},
        {"key": "description_score", "score": float(judge_res.get("description_score",0)) / 10.0},
        {"key": "background_score", "score": float(judge_res.get("background_score",0)) / 10.0},
        {"key": "contentions_score", "score": float(judge_res.get("contentions_score",0)) / 10.0},
        {"key": "conflict_score", "score": float(judge_res.get("conflict_score",0)) / 10.0},
        {"key": "extraction_score", "score": float(judge_res.get("extraction_score",0)) / 10.0},
        {"key": "body_score", "score": float(judge_res.get("body_score",0)) / 10.0}
    ]

def generate_report(ma_result, sp_result, actual_model):
    from loguru import logger
    logger.info("📄 [Report] 마크다운 실험 리포트 생성 중...")
    
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    report_md = f"""# 📊 통합 실험 결과 리포트 (Agentic vs. Baseline)
- **실험 일시**: {timestamp}
- **사용 모델**: {actual_model}

## 1. 📊 성능 및 총 소요량
| 지표 | Multi-Agent (Agentic) | Single-Pass (Baseline) |
| :--- | :--- | :--- |
| **소요 시간** | {ma_result.get('duration', 0):.2f}s | {sp_result.get('duration', 0):.2f}s |
| **프롬프트 토큰** | {ma_result.get('tokens', {}).get('prompt_tokens', 0):,} | {sp_result.get('tokens', {}).get('prompt_tokens', 0):,} |
| **완성 토큰** | {ma_result.get('tokens', {}).get('completion_tokens', 0):,} | {sp_result.get('tokens', {}).get('completion_tokens', 0):,} |

## 2. ⭐ 정밀 소수점 채점 (LangSmith Precision Score)
| 평가 항목 (10.0 만점) | Multi-Agent | Single-Pass |
| :--- | :--- | :--- |
"""
    ma_s = ma_result.get("scores", {})
    sp_s = sp_result.get("scores", {})
    
    for k in ["accuracy", "title_score", "description_score", "background_score", "contentions_score", "conflict_score", "extraction_score", "body_score"]:
        report_md += f"| {k} | {float(ma_s.get(k, 0)):.1f} | {float(sp_s.get(k, 0)):.1f} |\n"
    
    report_md += f"""
---
### 📝 심판 총평 (MA)
{ma_result.get('verdict', '')}

### 📝 심판 총평 (SP)
{sp_result.get('verdict', '')}

---
## 3. 📝 생성 결과물 샘플 (Article Body)
### [Multi-Agent (Agentic)]
{ma_result.get('output', '생성 실패')}

### [Single-Pass (Baseline)]
{sp_result.get('output', '생성 실패')}
"""
    latest_report_path = "tests/comparison_report.md"
    with open(latest_report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    
    results_dir = "tests/results"
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)
    safe_model = actual_model.replace(":", "_").replace("/", "_")
    history_report_path = f"{results_dir}/report_{time.strftime('%Y%m%d_%H%M%S')}_{safe_model}.md"
    with open(history_report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    
    print(f"✅ 리포트 생성 완료: {latest_report_path}")
    print(f"✅ 히스토리 기록 완료: {history_report_path}")

def main():
    client = Client()
    dataset_name = "News-Comparative-Analysis-Dataset"
    
    db = SessionLocal()
    with open("tests/full_test_data.json", "r", encoding="utf-8") as f:
        test_articles = json.load(f)
    sync_test_data(db, test_articles)
    db.close()

    # 실험 모드 설정 (여기서 모델을 완전 로컬(Qwen)으로 돌릴지, 제미나이로 돌릴지 제어 가능)
    ACTUAL_LLM_MODE = "local_only"
    print(f"🏁 [통합 벤치마크] 시작 (모드: {ACTUAL_LLM_MODE})")

    ma_report_data = {}
    sp_report_data = {}

    async def run_ma(inputs):
        start = time.time()
        inputs["llm_mode"] = ACTUAL_LLM_MODE
        res = await multi_agent_target(inputs)
        ma_report_data.update(res)
        ma_report_data['duration'] = time.time() - start
        return res

    async def run_sp(inputs):
        start = time.time()
        inputs["llm_mode"] = ACTUAL_LLM_MODE
        res = await single_pass_target(inputs)
        sp_report_data.update(res)
        sp_report_data['duration'] = time.time() - start
        return res

    print("\n[1/2] 멀티에이전트(MA) 실행 및 랭스미스 채점 중...")
    evaluate(
        lambda i: asyncio.run(run_ma(i)),
        data=dataset_name,
        evaluators=[precision_evaluator], 
        experiment_prefix=f"MA-{ACTUAL_LLM_MODE.upper()}",
    )

    print("\n[2/2] 싱글패스(SP) 실행 및 랭스미스 채점 중...")
    evaluate(
        lambda i: asyncio.run(run_sp(i)),
        data=dataset_name,
        evaluators=[precision_evaluator],
        experiment_prefix=f"SP-{ACTUAL_LLM_MODE.upper()}",
    )

    # 랭스미스 평가 시뮬레이션으로 로컬 데이터 추출
    print("\n[3/3] 로컬 리포트(.md) 분석 데이터 추출 중...")
    ma_eval = precision_evaluator(
        type('obj', (object,), {'outputs': ma_report_data})(), 
        type('obj', (object,), {'outputs': {'full_ground_truth': '...'}, 'inputs': {'articles': test_articles}})()
    )
    sp_eval = precision_evaluator(
        type('obj', (object,), {'outputs': sp_report_data})(), 
        type('obj', (object,), {'outputs': {'full_ground_truth': '...'}, 'inputs': {'articles': test_articles}})()
    )
    
    # 리스트 파싱 헬퍼 함수
    def parse_eval_list(eval_list):
        scores = {}
        verdict = ""
        if isinstance(eval_list, dict):
            eval_list = [eval_list]
        for item in eval_list:
            if item["key"] == "avg_precision_score":
                verdict = item.get("comment", "")
            else:
                scores[item["key"]] = item["score"] * 10.0
        return scores, verdict
        
    ma_scores, ma_verdict = parse_eval_list(ma_eval)
    sp_scores, sp_verdict = parse_eval_list(sp_eval)
    
    ma_report_data['scores'] = ma_scores
    ma_report_data['verdict'] = ma_verdict
    sp_report_data['scores'] = sp_scores
    sp_report_data['verdict'] = sp_verdict

    generate_report(ma_report_data, sp_report_data, ACTUAL_LLM_MODE)

if __name__ == "__main__":
    main()
