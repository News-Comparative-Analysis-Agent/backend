from sqlalchemy import Column, Integer, String, Boolean
from app.core.database import Base

class Publisher(Base):
    """
    언론사(Publisher) 테이블
    - 크롤링 대상이 되는 언론사 정보를 관리합니다.
    """
    __tablename__ = "publishers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False) # 언론사명 (예: '조선일보')
    code = Column(String, unique=True) # 내부 관리 코드 (예: 'chosun') - 사이트 식별용
    home_url = Column(String) # 홈페이지 URL
