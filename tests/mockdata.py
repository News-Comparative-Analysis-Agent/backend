from sqlalchemy.orm import Session
from app.core.database import SessionLocal, engine, Base
from app.domains.topics.models import Topic
from app.domains.publishers.models import Publisher
from app.domains.articles.models import Article, ArticleBody
from app.domains.stats.models import KeywordRelation
from datetime import datetime, timedelta, date
import random

# 이 파일은 DB에 Mock데이터를 삽입하는 테스트용 파일입니다.
# Article, Topic, Publisher, KeywordRelation 테이블에 데이터를 삽입합니다.
# 테스트 데이터는 대쉬보드에 사용되는 데이터를 위해서 작성되었습니다.

def insert_seed_data(db: Session):
    """
    DB 세션을 받아 초기 데이터를 삽입하는 재사용 가능한 함수
    """
    try:
        print("생성데이터 삽입중...")

        # 2. 토픽 생성 (Topics)
        topics_data = [
            {"name": "의대 증원", "keywords": ["의대", "2000명", "전공의", "파업", "의료대란", "복지부"]},
            {"name": "총선", "keywords": ["선거", "국회의원", "여당", "야당", "공천", "지지율"]},
            {"name": "반도체 보조금", "keywords": ["삼성전자", "SK하이닉스", "미국", "보조금", "칩스법", "투자"]},
            {"name": "금리 인하", "keywords": ["연준", "FOMC", "물가", "인플레이션", "파월"]}
        ]
        
        topic_objs = []
        for t_data in topics_data:
            topic = Topic(name=t_data["name"], keywords=t_data["keywords"])
            topic_objs.append(topic)
        
        db.add_all(topic_objs)
        db.commit()
        for t in topic_objs: db.refresh(t)
        print(f"생성되었습니다. {len(topic_objs)} Topics")

        # 2-1. 키워드 관계 생성 (KeywordRelation)
        today = date.today()
        k_relations = [
            # 의대 증원
            KeywordRelation(date=today, topic_id=topic_objs[0].id, keyword_a="의대", keyword_b="2000명", frequency=8),
            KeywordRelation(date=today, topic_id=topic_objs[0].id, keyword_a="의대", keyword_b="전공의", frequency=5),
            KeywordRelation(date=today, topic_id=topic_objs[0].id, keyword_a="전공의", keyword_b="파업", frequency=9),
            KeywordRelation(date=today, topic_id=topic_objs[0].id, keyword_a="파업", keyword_b="의료대란", frequency=7),
            KeywordRelation(date=today, topic_id=topic_objs[0].id, keyword_a="2000명", keyword_b="복지부", frequency=6),
            
            # 총선
            KeywordRelation(date=today, topic_id=topic_objs[1].id, keyword_a="선거", keyword_b="여당", frequency=5),
            KeywordRelation(date=today, topic_id=topic_objs[1].id, keyword_a="선거", keyword_b="야당", frequency=5),
            KeywordRelation(date=today, topic_id=topic_objs[1].id, keyword_a="여당", keyword_b="공천", frequency=8),
            KeywordRelation(date=today, topic_id=topic_objs[1].id, keyword_a="야당", keyword_b="공천", frequency=8),
            KeywordRelation(date=today, topic_id=topic_objs[1].id, keyword_a="여당", keyword_b="지지율", frequency=6),

            # 반도체
            KeywordRelation(date=today, topic_id=topic_objs[2].id, keyword_a="삼성전자", keyword_b="미국", frequency=8),
            KeywordRelation(date=today, topic_id=topic_objs[2].id, keyword_a="미국", keyword_b="보조금", frequency=10),
            KeywordRelation(date=today, topic_id=topic_objs[2].id, keyword_a="보조금", keyword_b="칩스법", frequency=9),

            # 금리
            KeywordRelation(date=today, topic_id=topic_objs[3].id, keyword_a="연준", keyword_b="금리", frequency=9),
            KeywordRelation(date=today, topic_id=topic_objs[3].id, keyword_a="금리", keyword_b="물가", frequency=7),
        ]
        db.add_all(k_relations)
        db.commit()
        print(f"Created {len(k_relations)} Keyword Relations")

        # 3. 언론사 생성 (Publishers)
        publishers = [
            Publisher(name="A일보", code="a_ilbo"), 
            Publisher(name="B뉴스", code="b_news"), 
            Publisher(name="C경제", code="c_eco"),  
            Publisher(name="D방송", code="d_tv")    
        ]
        db.add_all(publishers)
        db.commit()
        for p in publishers: db.refresh(p)
        print(f"Created {len(publishers)} Publishers")

        # 4. 기사 및 본문 생성 (Articles & Body)
        articles_raw = [
            {"t_idx": 0, "p_idx": 0, "title": "의대 2000명 증원 확정... 27년 만의 대수술", "bias": "conservative", "score": 8.0},
            {"t_idx": 0, "p_idx": 1, "title": "의료계 '총파업' 초읽기... 환자 곁 떠나나", "bias": "liberal", "score": 7.5},
            {"t_idx": 0, "p_idx": 3, "title": "정부 '법적 대응' vs 의협 '결사 항전'... 강대강 대치", "bias": "neutral", "score": 1.0},
            {"t_idx": 0, "p_idx": 0, "title": "필수의료 살리기 위해선 '고육지책' 불가피", "bias": "conservative", "score": 6.5},
            {"t_idx": 1, "p_idx": 1, "title": "야당 '정권 심판론' 점화... 수도권 표심 공략", "bias": "liberal", "score": 8.0},
            {"t_idx": 1, "p_idx": 0, "title": "여당 '운동권 청산' 깃발... 보수 결집 호소", "bias": "conservative", "score": 7.5},
            {"t_idx": 1, "p_idx": 3, "title": "총선 D-30, 여론조사 결과 접전... 부동층 향배는?", "bias": "neutral", "score": 2.0},
            {"t_idx": 2, "p_idx": 2, "title": "삼성전자, 미국 보조금 60억 달러 수혜 예상", "bias": "neutral", "score": 1.5},
            {"t_idx": 2, "p_idx": 1, "title": "미국 주도 공급망 재편의 명암... 기술 유출 우려", "bias": "liberal", "score": 6.0},
            {"t_idx": 3, "p_idx": 2, "title": "연준, 기준금리 동결... '인하 시점 신중해야'", "bias": "neutral", "score": 1.0},
            {"t_idx": 3, "p_idx": 3, "title": "고물가 둔화세 주춤... 금리 인하 기대감 후퇴", "bias": "neutral", "score": 3.0}
        ]

        article_objects = []
        for i, raw in enumerate(articles_raw):
            topic = topic_objs[raw["t_idx"]]
            pub = publishers[raw["p_idx"]]
            
            art = Article(
                topic_id=topic.id,
                publisher_id=pub.id,
                title=raw["title"],
                url=f"http://news.example.com/{i+1000}",
                published_at=datetime.now() - timedelta(hours=random.randint(1, 24)),
                summary=f"{raw['title']}에 대한 상세 내용입니다. 핵심 내용은... (AI 요약)",
                bias=raw["bias"],
                bias_score=raw["score"],
                key_arguments={"context": "Mock Data Analysis"}
            )
            # 본문 연결
            art.body = ArticleBody(raw_content=f"{raw['title']} - 기사 전문 텍스트입니다.")
            article_objects.append(art)

        db.add_all(article_objects)
        db.commit()
        print(f"생성되었습니다. {len(article_objects)} Articles")
        
        print("데이터 삽입 성공!")

    except Exception as e:
        print(f"삽입중 에러 발생!!: {e}")
        db.rollback()
        raise e

if __name__ == "__main__":
    # 기존 데이터 초기화 (스키마 변경 반영을 위해 Drop 후 Create)
    print("Resetting database...")
    Base.metadata.drop_all(bind=engine)
    
    # 테이블 생성
    Base.metadata.create_all(bind=engine)
    
    db: Session = SessionLocal()
    try:
        insert_seed_data(db)
    finally:
        db.close()
