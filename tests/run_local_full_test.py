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
from app.scroller.graph import create_comparison_graph, OverallState
from app.core.logger import logger
from langgraph.graph import START, END

def run_local_full_test():
    """
    tests/full_test_data.json을 로드하여 
    [클러스터 -> 명명 -> 청소 -> 분석 -> 기사 작성 -> 교정 -> 검수]
    """
    logger.info("🚀 [Local Full Test] JSON 데이터 기반 로컬 LLM 테스트 시작...")
    
    # 1. JSON 데이터 로드
    json_path = os.path.join(BASE_DIR, "tests", "full_test_data.json")
    if not os.path.exists(json_path):
        logger.error(f"❌ 테스트 데이터 파일을 찾을 수 없습니다: {json_path}")
        return
    
    with open(json_path, "r", encoding="utf-8") as f:
        test_articles = json.load(f)
    
    logger.info(f"📂 {len(test_articles)}개의 기사 로드 완료.")

    db: Session = SessionLocal()
    
    try:
        # 2. 기사 데이터를 DB에 미리 저장 (EvidenceAgent가 DB에서 조회할 수 있도록)
        from app.domains.articles.models import Article, ArticleBody
        from app.domains.publishers.models import Publisher
        from datetime import datetime
        from sqlalchemy import delete

        logger.info("💾 테스트 기사를 DB에 동기화 중...")
        formatted_articles = []
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

            # 딕셔너리로 즉시 캡처 (DetachedInstanceError 원천 차단)
            formatted_articles.append({
                "article_id": new_article.id,
                "title": item["title"],
                "content": item.get("content", item["title"]),
                "press": item["press"]
            })
        
        db.commit()
        logger.info(f"✅ {len(formatted_articles)}개의 기사가 DB와 연동되어 준비되었습니다.")

        # 4. 그래프 컴파일
        logger.info("🛠️  에이전트 그래프 컴파일 중...")
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
        
        # 5. 그래프 실행
        logger.info("🏃 그래프 워크플로우를 시작합니다.")
        
        config = {"configurable": {"thread_id": "local_test_run"}}
        final_state = app.invoke(initial_state, config=config)
        
        # 5. 결과 출력
        logger.success("🎉 [Local Full Test] 테스트 실행 종료!")
        
        # 최종 결과 확인
        issue_ids = final_state.get("all_issue_ids", [])
        if issue_ids:
            logger.success(f"✅ 생성된 이슈 IDs: {issue_ids}")
        
        tokens = final_state.get("total_tokens", {})
        logger.info(f"📊 사용된 총 토큰: {tokens}")
        
        # 생성된 기사 본문 요약 출력 (첫 번째 이슈 대상)
        if final_state.get("messages"):
            logger.info("📝 실행 메시지:")
            for msg in final_state["messages"][-5:]:
                logger.info(f"  - {msg}")

    except Exception as e:
        logger.critical(f"💥 테스트 실행 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    run_local_full_test()
