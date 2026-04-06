import os
import json
import asyncio
import time
from typing import List, Dict, Any
from langsmith import Client, evaluate
from dotenv import load_dotenv

load_dotenv()

from app.scroller.graph import create_comparison_graph
from app.agents.utils import call_llm_text, call_gemini
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
    llm_mode = inputs.get("llm_mode", "gemini_only")
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
            "media_views": agent_draft.get("media_views", []) if isinstance(agent_draft, dict) else [],
            "tokens": final_state.get("total_tokens", {})
        }
    finally:
        db.close()

async def single_pass_target(inputs: dict) -> dict:
    articles = inputs.get("articles", [])
    llm_mode = inputs.get("llm_mode", "gemini_only")
    
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
5. **형식**: 제목을 포함한 완성된 기사 텍스트만 출력하십시오.
"""
    start_time = time.time()
    result_text, tokens = call_llm_text(prompt, "7B", {"llm_mode": llm_mode})
    duration = time.time() - start_time
    
    return {
        "output": result_text,
        "duration": duration,
        "tokens": {"prompt_tokens": tokens.get("prompt_tokens", 0), "completion_tokens": tokens.get("completion_tokens", 0)}
    }

def precision_evaluator(run, example) -> dict:
    """Gemini 2.0을 랭스미스 심판으로 사용하여 0.0~10.0의 소수점 점수를 산출합니다."""
    ground_truth = example.outputs.get("full_ground_truth", "")
    prediction = run.outputs.get("output", "")
    
    # 조기 방어: 결과물이 도출되지 않았을 경우, 불필요한 LLM 호출 없이 0점으로 채점
    if not prediction or len(prediction.strip()) < 10:
        return {
            "key": "avg_precision_score",
            "score": 0.0,
            "comment": "[치명적 오류] 멀티에이전트가 기사 생성에 실패하여 평가 대상이 존재하지 않습니다.",
            "accuracy": 0.0,
            "frame": 0.0,
            "logic": 0.0,
            "overall": 0.0
        }
    
    prompt = f"""
    당신은 랭스미스 평가관(Judge)입니다. [원본 데이터]와 [평가 대상]을 대조하여 4가지 지표에 대해 0.0점부터 10.0점까지 소수점 첫째 자리(예: 8.7, 9.2)로 깐깐하게 채점하세요.

    [원본 데이터 (Ground Truth)]
    {ground_truth}
    
    [평가 대상 결과물]
    {prediction}
    
    [평가 지표 (0.0~10.0)]
    1. accuracy: 원본 기사로부터 이탈하거나 할루시네이션이 발생하지 않았는가? (팩트 왜곡 시 5.0 이하 즉시 감점)
    2. frame: 언론사별 논조 차이를 예리하게 포착했는가?
    3. logic: 문장 간 연결이 자연스럽고 논리적인가?
    4. overall: 수준 높은 통합 비평 기사로서의 전반적인 완성도는 어떠한가?
    
    오직 JSON 형식으로만 응답하세요:
    {{
      "accuracy": "[0.0 ~ 10.0 사이의 채점된 소수점]",
      "frame": "[0.0 ~ 10.0 사이의 채점된 소수점]",
      "logic": "[0.0 ~ 10.0 사이의 채점된 소수점]",
      "overall": "[0.0 ~ 10.0 사이의 채점된 소수점]",
      "verdict": "각 점수에 대한 상세한 심사평 요약"
    }}
    """
    judge_res, _ = call_gemini(prompt)
    if not isinstance(judge_res, dict):
        import re
        try:
             json_str = re.search(r'\{.*\}', judge_res, re.DOTALL).group()
             judge_res = json.loads(json_str)
        except:
             judge_res = {"verdict": "Parsing error", "accuracy": 0.0, "frame": 0.0, "logic": 0.0, "overall": 0.0}
             
    avg_score = (float(judge_res.get("accuracy",0)) + float(judge_res.get("frame",0)) + float(judge_res.get("logic",0)) + float(judge_res.get("overall",0))) / 4.0
    return {
        "key": "avg_precision_score",
        "score": avg_score / 10.0, # 랭스미스는 0~1 정규화를 선호
        "comment": judge_res.get("verdict", ""),
        "accuracy": float(judge_res.get("accuracy",0)),
        "frame": float(judge_res.get("frame",0)),
        "logic": float(judge_res.get("logic",0)),
        "overall": float(judge_res.get("overall",0))
    }

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
    
    for k in ["accuracy", "frame", "logic", "overall"]:
        report_md += f"| {k.capitalize()} | {float(ma_s.get(k, 0)):.1f} | {float(sp_s.get(k, 0)):.1f} |\n"
    
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
    ma_eval = precision_evaluator(type('obj', (object,), {'outputs': ma_report_data}), 
                                  type('obj', (object,), {'outputs': {'full_ground_truth': '...'}}))
    sp_eval = precision_evaluator(type('obj', (object,), {'outputs': sp_report_data}), 
                                  type('obj', (object,), {'outputs': {'full_ground_truth': '...'}}))
    
    ma_report_data['scores'] = ma_eval
    ma_report_data['verdict'] = ma_eval.get('comment', '')
    sp_report_data['scores'] = sp_eval
    sp_report_data['verdict'] = sp_eval.get('comment', '')

    generate_report(ma_report_data, sp_report_data, ACTUAL_LLM_MODE)

if __name__ == "__main__":
    main()
