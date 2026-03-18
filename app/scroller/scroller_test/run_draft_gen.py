import sys
import os
from sqlalchemy.orm import Session
from sqlalchemy import desc
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(BASE_DIR)

load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.core.database import SessionLocal
from app.domains.issues.models import IssueLabel
# SQLAlchemy 관계 매핑시 참조할 Article 모델 또한 명시적으로 import 해줍니다.
from app.domains.articles.models import Article 
from google import genai

# Gemini API 설정
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=GOOGLE_API_KEY) if GOOGLE_API_KEY else None

def generate_draft_for_issue(issue: IssueLabel) -> str:
    """
    특정 이슈의 background와 핵심 쟁점을 바탕으로 기사 초안을 작성합니다.
    """
    prompt = f"""
당신은 전문적인 저널리스트입니다. 아래 제공된 주요 이슈 정보를 바탕으로 논리적이고 중립적인 뉴스 기사의 초안을 작성해주세요.
바로 복사해서 붙여넣을 수 있도록 불필요한 인사말 없이 기사 본문만 출력해주세요. 마크다운 해딩 등은 제외.

[이슈 정보]
* 이슈명: {issue.name}
* 배경 설명: {issue.description or '정보 없음'}
* 핵심 발단/배경: {issue.background or '정보 없음'}
* 주요 쟁점: {issue.core_contentions or '정보 없음'}

[작성 가이드]
1. 도입부: 사건의 핵심 요약
2. 전개: 배경 및 주요 쟁점 (각 측의 입장 포함)
3. 결론: 향후 전망 및 시사점
길이는 약 600~800자 내외로 작성해주세요.
"""
    try:
        from app.core.logger import log_llm_event
        log_llm_event("DraftGen", f"Generating draft for issue: {issue.name}", details=prompt)
        
        if not client:
            return "Gemini Client not initialized"

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        log_llm_event("DraftGen", f"Response received for issue: {issue.name}", details=response.text)
        return response.text.strip()
    except Exception as e:
        log_llm_event("DraftGen", f"Error generating draft for {issue.name}: {e}", type="ERROR")
        logger.error(f"[{issue.name}] 초안 생성 중 오류 발생: {e}")
        return ""

from app.scroller.graph import create_comparison_graph

def run_draft_generation():
    log_llm_event("DraftGen", "상위 5개 이슈 초안 자동 생성 시작 (Multi-Agent)")
    logger.info("🚀 [Draft Gen] 상위 5개 이슈 다중 에이전트 기반 초안 생성 시작...")
    db: Session = SessionLocal()
    
    # 그래프 컴파일
    comparison_app = create_comparison_graph(db)
    
    try:
        # 최근 이슈 중, 기사 수가 가장 많은 상위 5개 가져오기
        # (원한다면 created_at 조건을 추가하여 오늘 생성된 이슈만 필터링 가능)
        top_issues = db.query(IssueLabel).order_by(desc(IssueLabel.total_count)).limit(5).all()
        
        if not top_issues:
            logger.info("ℹ️ 생성된 이슈가 없습니다.")
            return

        generated_count = 0
        for idx, issue in enumerate(top_issues, start=1):
            if issue.pre_generated_draft:
                logger.info(f"{idx}. [{issue.name}] - 이미 초안이 존재합니다. 건너뜁니다.")
                continue
                
            logger.info(f"{idx}. [{issue.name}] (기사 수: {issue.total_count}) - Multi-Agent 분석 및 초안 생성 중...")
            
            # LangGraph 초기 상태 주입 (5단계 에이전트 인터페이스에 맞춤)
            initial_state = {
                "llm_mode": "gemini_only", 
                "issue_id": issue.id,
                "articles": [],
                "claim_cards": [],
                "structured_issues": [],
                "draft_article": {},
                "edited_article": {},
                "edit_log": {},
                "judge_status": "",
                "judge_feedback": {},
                "retry_count": 0,
                "messages": [],
                "error": ""
            }
            
            config = {"configurable": {"thread_id": f"issue_draft_{issue.id}"}}
            try:
                final_state = comparison_app.invoke(initial_state, config=config)
                
                # 에이전트들이 평가 루프를 거치고 완성한 최종 검수 완료 기사
                draft_data = final_state.get("edited_article", {})
                
                if draft_data and "오류가 발생" not in str(draft_data):
                    # DB 저장을 위해 dict를 JSON 문자열로 변환
                    import json
                    issue.pre_generated_draft = json.dumps(draft_data, ensure_ascii=False)
                    generated_count += 1
                    logger.success(f"    ↳ 작성 완료! (재시도 횟수: {final_state.get('retry_count')})")
                else:
                    logger.warning(f"    ↳ 작성 실패 또는 에러 발생")
            except Exception as e:
                logger.error(f"    ↳ 에이전트 그래프 실행 중 에러: {e}")
                
        if generated_count > 0:
            db.commit()
            logger.success(f"✅ 총 {generated_count}개의 이슈 초안이 성공적으로 저장되었습니다.")
        else:
            logger.info("❕ 새롭게 생성된 초안이 없습니다.")
            
    except Exception as e:
        logger.error(f"❌ [Draft Gen] 프로세스 중 오류 발생: {e}")
        db.rollback()
    finally:
        db.close()
        log_llm_event("DraftGen", "초안 자동 생성 파이프라인 종료")
        logger.info("🎉 [Draft Gen] 초안 자동 생성 파이프라인이 종료되었습니다.")

if __name__ == "__main__":
    run_draft_generation()
