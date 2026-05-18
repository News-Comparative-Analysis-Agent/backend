import sys
import os
import json

# 프로젝트 루트 디렉토리를 sys.path에 추가
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from sqlalchemy.orm import Session
from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.core.database import SessionLocal
from app.scroller.graph import create_comparison_graph
from app.core.logger import logger

def run_local_politics_test():
    """
    tests/test_data_politic.json을 로드하여
    정치 모드("politics") 상태 코드를 바탕으로
    [클러스터 -> 명명 -> 청소 -> 분석(Evidence 추출 및 사건 핵심 쟁점 도출)] 파이프라인 진행 테스트
    """
    logger.info("🚀 [Local Politics Test] 정치 현안 데이터 기반 로컬 파이프라인 테스트 시작...")
    
    # 1. 정치용 JSON 테스트 데이터 로드
    json_path = os.path.join(BASE_DIR, "tests", "test_data_politic.json")
    if not os.path.exists(json_path):
        logger.error(f"❌ 테스트 데이터 파일을 찾을 수 없습니다: {json_path}")
        return
    
    with open(json_path, "r", encoding="utf-8") as f:
        test_articles = json.load(f)
    
    logger.info(f"📂 {len(test_articles)}개의 정치 기사 로드 완료.")

    db: Session = SessionLocal()
    
    try:
        # 2. 기사 데이터를 DB에 미리 저장 (EvidenceAgent가 DB에서 조회할 수 있도록 함)
        from app.domains.articles.models import Article, ArticleBody, ArticleClaim
        from app.domains.publishers.models import Publisher
        from app.domains.issues.models import IssueLabel
        from datetime import datetime
        from sqlalchemy import delete

        logger.info("💾 테스트용 정치 기사 및 이슈 테이블 초기화 중...")
        db.execute(delete(ArticleBody))
        db.execute(delete(ArticleClaim))
        db.execute(delete(Article))
        db.execute(delete(IssueLabel))
        db.flush()
        
        formatted_articles = []
        for item in test_articles:
            # 언론사 확인 및 생성
            publisher = db.query(Publisher).filter(Publisher.name == item["press"]).first()
            if not publisher:
                publisher = Publisher(name=item["press"], code=item["press"])
                db.add(publisher)
                db.flush()
            
            # 기사 생성 (Get or Create 패턴)
            existing_article = db.query(Article).filter(Article.url == item["url"]).first()
            
            # 날짜 파싱
            pub_date = datetime.now()
            if item.get("published_at"):
                try:
                    pub_date = datetime.strptime(item["published_at"], "%Y-%m-%d")
                except ValueError:
                    pass

            if existing_article:
                new_article = existing_article
                new_article.title = item["title"]
                new_article.published_at = pub_date
                new_article.issue_label_id = None # 초기화하여 다시 클러스터링되도록 함
                db.flush()
            else:
                new_article = Article(
                    title=item["title"],
                    url=item["url"],
                    publisher_id=publisher.id,
                    published_at=pub_date,
                    issue_label_id=None
                )
                db.add(new_article)
                db.flush()
            
            # 본문 저장
            db.execute(delete(ArticleBody).where(ArticleBody.article_id == new_article.id))
            db.flush()
            
            new_body = ArticleBody(article_id=new_article.id, raw_content=item.get("content", item["title"]))
            db.add(new_body)
            db.flush()

            # 딕셔너리로 즉시 캡처 (DetachedInstanceError 원천 차단)
            formatted_articles.append({
                "article_id": new_article.id,
                "title": item["title"],
                "content": item.get("content", item["title"]),
                "press": item["press"]
            })
        
        db.commit()
        logger.info(f"✅ {len(formatted_articles)}개의 정치 기사가 DB와 연동되어 준비되었습니다.")

        # 3. 그래프 컴파일
        logger.info("🛠️  에이전트 그래프 컴파일 중...")
        app = create_comparison_graph(db)
        
        # 4. 초기 상태 설정 ("article_mode"를 "politics"로 지정!)
        initial_state = {
            "llm_mode": "local_only",
            "article_mode": "politics",  # 핵심 정치 파이프라인 트리거!
            "issue_id": None,
            "all_issue_ids": [],
            "raw_articles": [],
            "unclustered_articles": formatted_articles, 
            "clustered_topics": [],
            "total_tokens": {"prompt_tokens": 0, "completion_tokens": 0},
            "messages": [],
            "error": ""
        }
        
        # 5. 그래프 실행
        logger.info("🏃 정치 그래프 워크플로우를 시작합니다. (클러스터부터 이슈 분석까지 일괄 진행)")
        
        config = {"configurable": {"thread_id": "politics_local_test_run"}, "recursion_limit": 150}
        final_state = app.invoke(initial_state, config=config)
        
        # 6. 결과 출력
        logger.success("🎉 [Local Politics Test] 테스트 실행 종료!")
        
        if final_state.get("error"):
            logger.error(f"❌ 중단 원인: {final_state['error']}")
            return

        issue_ids = final_state.get("all_issue_ids", [])
        if issue_ids:
            logger.success(f"✅ 생성된 정치 이슈 IDs: {issue_ids}")
            
            # DB에서 생성된 결과를 상세히 출력하여 검증
            from app.domains.issues.models import IssueLabel
            from app.domains.articles.models import Article
            
            for iid in issue_ids:
                issue = db.query(IssueLabel).filter(IssueLabel.id == iid).first()
                if issue:
                    logger.info("==================================================")
                    logger.success(f"📌 생성된 이슈 명칭: {issue.name}")
                    logger.success(f"⚙️  분석 상태 (status): {issue.status}")
                    logger.info(f"📝 이슈 요약 설명 (description): {issue.description}")
                    logger.info(f"💡 이슈 배경 설명 (background): {issue.background}")
                    logger.success(f"🔥 사건의 핵심 쟁점 (conflict_summary): {issue.conflict_summary}")
                    
                    # 연결된 기사들의 분석 결과 (주장 및 근거) 확인
                    from app.domains.articles.models import ArticleClaim
                    claims = db.query(ArticleClaim).filter(ArticleClaim.issue_id == iid).all()
                    logger.info(f"📰 연결된 기사 분석 내역 (총 {len(claims)}건):")
                    for clm in claims:
                        logger.info(f"  - [{clm.press}] {clm.article.title if clm.article else clm.press}")
                        logger.info(f"    └ 📢 주장 (claim): {clm.claim}")
                        logger.info(f"    └ 📝 추출 근거 (evidence):")
                        if clm.evidence:
                            for line in clm.evidence.split('\n'):
                                if line.strip():
                                    logger.info(f"      {line.strip()}")
                    logger.info("==================================================")
        
        tokens = final_state.get("total_tokens", {})
        logger.info(f"📊 사용된 총 토큰: {tokens}")
        
        if final_state.get("messages"):
            logger.info("📝 실행 메시지:")
            for msg in final_state["messages"][-10:]:
                logger.info(f"  - {msg}")

    except Exception as e:
        logger.critical(f"💥 테스트 실행 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    run_local_politics_test()
