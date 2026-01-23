from sqlalchemy.orm import Session
from app.core.database import SessionLocal, engine, Base
from app.domains.issues.models import IssueLabel
from app.domains.topics.models import Topic
from app.domains.publishers.models import Publisher
from app.domains.articles.models import Article, ArticleBody
from app.domains.keywordrelation.models import KeywordRelation
from datetime import date, datetime, timedelta
import random

# 이 파일은 DB에 Mock데이터를 삽입하는 테스트용 파일입니다.
# Article, Topic, IssueLabel, Publisher, KeywordRelation 테이블에 데이터를 삽입합니다.

def insert_seed_data(db: Session):
    """
    DB 세션을 받아 초기 데이터를 삽입하는 재사용 가능한 함수
    """
    try:
        print("생성데이터 삽입중...")

        # 1. 토픽 생성 (Topics - 정책/대주제)
        # keywords가 Topic 모델에서 제거되었으므로 topic_text만 사용
        topics_data = [
            {"topic": "의대 증원 정책"},
            {"topic": "총선 및 정국"},
            {"topic": "반도체 산업 지원"},
            {"topic": "고물가 및 금리"}
        ]
        
        topic_objs = []
        for t_data in topics_data:
            topic = Topic(topic=t_data["topic"])
            topic_objs.append(topic)
        
        db.add_all(topic_objs)
        db.commit()
        for t in topic_objs: db.refresh(t)
        print(f"생성되었습니다. {len(topic_objs)} Topics")

        # 2. 이슈 레이블 생성 (IssueLabels - 구체적 사건/클러스터)
        # 키워드는 여기서 관리
        issues_data = [
            {"name": "전공의 집단 사직", "keywords": ["전공의", "사직서", "집단행동", "의료대란", "응급실"]},
            {"name": "의대 2000명 증원 확정", "keywords": ["2000명", "증원", "복지부", "필수의료", "배분"]},
            {"name": "여당 공천 갈등", "keywords": ["공천", "여당", "한동훈", "친윤", "컷오프"]},
            {"name": "야당 정권 심판론", "keywords": ["심판", "이재명", "독재", "민생", "탄핵"]},
            {"name": "삼성전자 보조금 수령", "keywords": ["삼성전자", "보조금", "미국", "텍사스", "투자"]},
            {"name": "연준 금리 동결", "keywords": ["연준", "파월", "금리", "인플레이션", "동결"]}
        ]

        issue_objs = []
        for i_data in issues_data:
            issue = IssueLabel(name=i_data["name"], keyword=i_data["keywords"], total_count=0)
            issue_objs.append(issue)
        
        db.add_all(issue_objs)
        db.commit()
        for i in issue_objs: db.refresh(i)
        print(f"생성되었습니다. {len(issue_objs)} IssueLabels")

        # 2-1. 키워드 관계 생성 (KeywordRelation) - IssueLabel에 연결
        today = date.today()
        # 간단하게 이슈별로 키워드 조합해서 관계 생성
        k_relations = []
        for issue in issue_objs:
            keywords = issue.keyword
            if len(keywords) >= 2:
                # 0-1, 1-2, 2-3... 순차적으로 연결
                for i in range(len(keywords)-1):
                    rel = KeywordRelation(
                        date=today,
                        issue_label_id=issue.id,
                        keyword_a=keywords[i],
                        keyword_b=keywords[i+1],
                        frequency=random.randint(5, 15)
                    )
                    k_relations.append(rel)
                    
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

        # 4. 기사 생성 (Articles)
        # 기사는 Topic(대주제)와 IssueLabel(소사건) 모두에 연결
        # 이슈 인덱스 매핑: 0,1->Topic0 | 2,3->Topic1 | 4->Topic2 | 5->Topic3
        issue_to_topic_map = {0:0, 1:0, 2:1, 3:1, 4:2, 5:3}

        articles_data = []
        # 각 이슈별로 기사 3개씩 생성
        for i_idx, issue in enumerate(issue_objs):
            t_idx = issue_to_topic_map.get(i_idx, 0)
            topic = topic_objs[t_idx]
            
            for k in range(3):
                p_idx = random.randint(0, 3)
                pub = publishers[p_idx]
                title = f"[{issue.name}] 관련 보도 {k+1}: {issue.keyword[0]} 이슈"
                
                art = Article(
                    topic_id=topic.id,
                    issue_label_id=issue.id,
                    publisher_id=pub.id,
                    title=title,
                    url=f"http://news.example.com/{issue.id}_{k}",
                    published_at=datetime.now() - timedelta(hours=random.randint(1, 48)),
                    summary=f"{title}에 대한 요약입니다.",
                    bias=random.choice(["conservative", "liberal", "neutral"]),
                    bias_score=round(random.uniform(0, 10), 1),
                    key_arguments=f"핵심 논점: {issue.keyword[0]} vs {issue.keyword[1]}"
                    # keywords 컬럼은 Article에서 제거됨
                )
                
                # 본문
                art.body = ArticleBody(raw_content=f"{title} 본문 내용입니다...")
                articles_data.append(art)

        db.add_all(articles_data)
        db.commit()
        
        # 기사 수 업데이트 (Topic & IssueLabel)
        for topic in topic_objs:
            count = db.query(Article).filter(Article.topic_id == topic.id).count()
            # topic.total_count = count  <-- removed field
            
        for issue in issue_objs:
            count = db.query(Article).filter(Article.issue_label_id == issue.id).count()
            issue.total_count = count
            
        db.commit()
        print(f"생성되었습니다. {len(articles_data)} Articles")
        
        print("데이터 삽입 성공!")

    except Exception as e:
        print(f"삽입중 에러 발생!!: {e}")
        db.rollback()
        raise e

if __name__ == "__main__":
    from app.domains.issues.models import IssueLabel
    from app.domains.keywordrelation.models import KeywordRelation
    
    # 기존 데이터 초기화
    print("Resetting database...")
    Base.metadata.drop_all(bind=engine)
    
    # 테이블 생성
    Base.metadata.create_all(bind=engine)
    
    db: Session = SessionLocal()
    try:
        insert_seed_data(db)
    finally:
        db.close()
