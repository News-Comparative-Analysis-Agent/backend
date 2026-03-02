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
import google.generativeai as genai

# Gemini API 설정 (langgraph에서는 node를 통해 호출하지만, 여기서는 독립 스크립트로 직접 호출)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
else:
    print("❌ GOOGLE_API_KEY가 설정되지 않았습니다.")

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
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"[{issue.name}] 초안 생성 중 오류 발생: {e}")
        return ""

def run_draft_generation():
    print("🚀 [Draft Gen] 상위 5개 이슈 초안 자동 생성을 시작합니다...")
    db: Session = SessionLocal()
    
    try:
        # 최근 이슈 중, 기사 수가 가장 많은 상위 5개 가져오기
        # (원한다면 created_at 조건을 추가하여 오늘 생성된 이슈만 필터링 가능)
        top_issues = db.query(IssueLabel).order_by(desc(IssueLabel.total_count)).limit(5).all()
        
        if not top_issues:
            print("생성된 이슈가 없습니다.")
            return

        generated_count = 0
        for idx, issue in enumerate(top_issues, start=1):
            if issue.pre_generated_draft:
                print(f"{idx}. [{issue.name}] - 이미 초안이 존재합니다. 건너뜁니다.")
                continue
                
            print(f"{idx}. [{issue.name}] (기사 수: {issue.total_count}) - 초안 생성 중...")
            draft_text = generate_draft_for_issue(issue)
            
            if draft_text:
                issue.pre_generated_draft = draft_text
                generated_count += 1
                
        if generated_count > 0:
            db.commit()
            print(f"✅ 총 {generated_count}개의 이슈 초안이 성공적으로 저장되었습니다.")
        else:
            print("❕ 새롭게 생성된 초안이 없습니다.")
            
    except Exception as e:
        print(f"❌ [Draft Gen] 프로세스 중 오류 발생: {e}")
        db.rollback()
    finally:
        db.close()
        print("🎉 [Draft Gen] 초안 자동 생성 파이프라인이 종료되었습니다.")

if __name__ == "__main__":
    run_draft_generation()
