from sqlalchemy.orm import Session
from app.core.database import SessionLocal, engine, Base
from app.domains.topics.models import Topic
from app.domains.publishers.models import Publisher
from app.domains.articles.models import Article, ArticleBody
from datetime import datetime, timedelta
import random

def seed_data():
    # 1. 테이블 생성 (없는 경우)
    Base.metadata.create_all(bind=engine)
    
    db: Session = SessionLocal()
    try:
        print("Seeding data...")

        # 2. 토픽 생성 (Topics) + 그래프 데이터 (Network Visualization)
        topics_data = [
            {
                "name": "의대 증원",
                "keywords": ["의대", "2000명", "전공의", "파업", "의료대란", "복지부"],
                "graph_data": {
                    "nodes": [
                        {"id": "의대", "group": 1, "value": 20},
                        {"id": "2000명", "group": 1, "value": 15},
                        {"id": "전공의", "group": 2, "value": 18},
                        {"id": "파업", "group": 2, "value": 12},
                        {"id": "의료대란", "group": 3, "value": 10},
                        {"id": "복지부", "group": 1, "value": 14}
                    ],
                    "links": [
                        {"source": "의대", "target": "2000명", "value": 8},
                        {"source": "의대", "target": "전공의", "value": 5},
                        {"source": "전공의", "target": "파업", "value": 9},
                        {"source": "파업", "target": "의료대란", "value": 7},
                        {"source": "2000명", "target": "복지부", "value": 6}
                    ]
                }
            },
            {
                "name": "총선",
                "keywords": ["선거", "국회의원", "여당", "야당", "공천", "지지율"],
                "graph_data": {
                    "nodes": [
                        {"id": "선거", "group": 1, "value": 25},
                        {"id": "여당", "group": 2, "value": 15},
                        {"id": "야당", "group": 2, "value": 15},
                        {"id": "공천", "group": 3, "value": 12},
                        {"id": "지지율", "group": 3, "value": 10}
                    ],
                    "links": [
                        {"source": "선거", "target": "여당", "value": 5},
                        {"source": "선거", "target": "야당", "value": 5},
                        {"source": "여당", "target": "공천", "value": 8},
                        {"source": "야당", "target": "공천", "value": 8},
                        {"source": "여당", "target": "지지율", "value": 6}
                    ]
                }
            },
             {
                "name": "반도체 보조금",
                "keywords": ["삼성전자", "SK하이닉스", "미국", "보조금", "칩스법", "투자"],
                "graph_data": {
                     "nodes": [
                        {"id": "삼성전자", "group": 1, "value": 20},
                        {"id": "미국", "group": 2, "value": 18},
                        {"id": "보조금", "group": 2, "value": 15},
                        {"id": "칩스법", "group": 2, "value": 12}
                    ],
                    "links": [
                        {"source": "삼성전자", "target": "미국", "value": 8},
                        {"source": "미국", "target": "보조금", "value": 10},
                        {"source": "보조금", "target": "칩스법", "value": 9}
                    ]
                }
            },
            {
                "name": "금리 인하",
                "keywords": ["연준", "FOMC", "물가", "인플레이션", "파월"],
                "graph_data": {
                     "nodes": [
                        {"id": "연준", "group": 1, "value": 20},
                        {"id": "금리", "group": 1, "value": 18},
                        {"id": "물가", "group": 2, "value": 15},
                        {"id": "파월", "group": 3, "value": 12}
                    ],
                    "links": [
                        {"source": "연준", "target": "금리", "value": 9},
                        {"source": "금리", "target": "물가", "value": 7}
                    ]
                }
            }
        ]
        
        topic_objs = []
        for t_data in topics_data:
            topic = Topic(name=t_data["name"], keywords=t_data["keywords"], graph_data=t_data["graph_data"])
            topic_objs.append(topic)
        
        db.add_all(topic_objs)
        db.commit()
        for t in topic_objs: db.refresh(t)
        print(f"Created {len(topic_objs)} Topics")

        # 3. 언론사 생성 (Publishers)
        publishers = [
            Publisher(name="A일보", code="a_ilbo"), # 보수
            Publisher(name="B뉴스", code="b_news"), # 진보
            Publisher(name="C경제", code="c_eco"),  # 경제/중도
            Publisher(name="D방송", code="d_tv")    # 방송/중도
        ]
        db.add_all(publishers)
        db.commit()
        for p in publishers: db.refresh(p)
        print(f"Created {len(publishers)} Publishers")

        # 4. 기사 및 본문 생성 (Articles & Body) - 10개 이상 생성
        articles_raw = [
            # 의대 증원
            {"t_idx": 0, "p_idx": 0, "title": "의대 2000명 증원 확정... 27년 만의 대수술", "bias": "conservative", "score": 8.0},
            {"t_idx": 0, "p_idx": 1, "title": "의료계 '총파업' 초읽기... 환자 곁 떠나나", "bias": "liberal", "score": 7.5},
            {"t_idx": 0, "p_idx": 3, "title": "정부 '법적 대응' vs 의협 '결사 항전'... 강대강 대치", "bias": "neutral", "score": 1.0},
            {"t_idx": 0, "p_idx": 0, "title": "필수의료 살리기 위해선 '고육지책' 불가피", "bias": "conservative", "score": 6.5},
            
            # 총선
            {"t_idx": 1, "p_idx": 1, "title": "야당 '정권 심판론' 점화... 수도권 표심 공략", "bias": "liberal", "score": 8.0},
            {"t_idx": 1, "p_idx": 0, "title": "여당 '운동권 청산' 깃발... 보수 결집 호소", "bias": "conservative", "score": 7.5},
            {"t_idx": 1, "p_idx": 3, "title": "총선 D-30, 여론조사 결과 접전... 부동층 향배는?", "bias": "neutral", "score": 2.0},
            
            # 반도체
            {"t_idx": 2, "p_idx": 2, "title": "삼성전자, 미국 보조금 60억 달러 수혜 예상", "bias": "neutral", "score": 1.5},
            {"t_idx": 2, "p_idx": 1, "title": "미국 주도 공급망 재편의 명암... 기술 유출 우려", "bias": "liberal", "score": 6.0},
            
            # 금리
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
        print(f"Created {len(article_objects)} Articles with Body")
        
        print("데이터가 성공적으로 삽입됐습니다")

    except Exception as e:
        print(f"An error occurred: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_data()
