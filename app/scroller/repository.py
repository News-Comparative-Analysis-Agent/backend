# app/scroller/repository.py
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta
from app.domains.articles.models import Article
from app.domains.articles.models import ArticleBody
from app.domains.publishers.models import Publisher
from app.domains.issues.models import IssueLabel

class ScrollerRepository:
    
    def __init__(self, db: Session):
        self.db = db



    def get_or_create_publisher(self, press_name: str) -> Publisher:
        publisher = self.db.query(Publisher).filter(Publisher.name == press_name).first()
        if not publisher:
            publisher = Publisher(name=press_name, code=press_name)
            self.db.add(publisher)
            self.db.flush()
        return publisher

    def is_article_exists(self, url: str) -> bool:
        # url과 기사를 매칭에 이미 있는지 확인
        existing = self.db.query(Article).filter(Article.url == url).first()
        return existing is not None

    def save_article_with_body(self, publisher_id: int, title: str, url: str, image_urls: list, published_at: datetime, content: str,
                                summary: str = None, bias: str = None, bias_score: float = None, reporter: str = None) -> Article:
            # 기사 본문을 데베에 저장!!
            article = Article(
                publisher_id=publisher_id,
                title=title,
                url=url,
                image_urls=image_urls,
                published_at=published_at,
                summary=summary,
                bias=bias,
                bias_score=bias_score,
                reporter=reporter
            )
            self.db.add(article)
            self.db.flush()

            body = ArticleBody(
                article_id=article.id,
                raw_content=content
            )
            self.db.add(body)
            return article

    def get_unclustered_articles(self) -> list[Article]:
        # 이슈 라벨이 부여되지 않은 기사를 가져온다(기사를 수집-> 클러스터링할 때 이슈 라벨 부여!!)
        return self.db.query(Article).filter(Article.issue_label_id == None).all()
        
    def search_articles_by_keyword(self, keyword: str, limit: int = 15) -> list[Article]:
        # 기사를 최신순으로 검색한다!! 
        search_pattern = f"%{keyword}%"
        return self.db.query(Article).outerjoin(ArticleBody).filter(
            (Article.title.ilike(search_pattern)) | 
            (ArticleBody.raw_content.ilike(search_pattern))
        ).order_by(Article.published_at.desc()).limit(limit).all()
                
    def save_issue_and_relations(self, ai_label: str, description: str, count: int, 
                                    article_ids_to_update: list, 
                                    background: str = None, core_contentions: str = None, media_ratio: str = None) -> IssueLabel:
            # 새로운 이슈를 생성하고, 매칭되는 기사들의 id를 업데이트
            issue = IssueLabel(
                name=ai_label,
                description=description,
                total_count=int(count),
                background=background,
                core_contentions=core_contentions,
                media_ratio=media_ratio,
                created_at=datetime.now()
            )
            self.db.add(issue)
            self.db.flush() 

            # 연관된 기존 기사들의 issue_label_id 업데이트
            self.db.query(Article).filter(Article.id.in_(article_ids_to_update)).update(
                {"issue_label_id": issue.id}, synchronize_session=False
            )
            return issue

    def truncate_all_data(self):
        # db id를 리셋!! 
        self.db.execute(text("TRUNCATE TABLE issue_labels, articles RESTART IDENTITY CASCADE"))
