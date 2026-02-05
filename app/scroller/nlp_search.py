import requests
import os
from dotenv import load_dotenv
import json
import google.generativeai as genai
from newspaper import Article
from datetime import datetime
from collections import Counter
import html
import re


# Load .env from backend root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(BASE_DIR, ".env"))

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

genai.configure(api_key=GOOGLE_API_KEY)

class NewsBriefingAgent:
    def __init__(self):
        self.headers = {
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
        }

    def search_naver(self, query, display=10):
        """ 네이버 뉴스 검색 """
        url = "https://openapi.naver.com/v1/search/news.json"
        params = {"query": query, "display": display, "sort": "date"}
        try:
            res = requests.get(url, headers=self.headers, params=params)
            return res.json().get('items', []) if res.status_code == 200 else []
        except:
            return []

    def fetch_full_content(self, url):
        """ 기사 본문 스크래핑 (상위 기사용) """
        try:
            article = Article(url, language='ko')
            article.download()
            article.parse()
            if len(article.text) < 50: return None
            return article.text
        except:
            return None

    def generate_briefing(self, query, articles_data):
        try:
            model = genai.GenerativeModel('gemini-2.0-flash')
            
            # AI에게 줄 컨텍스트 데이터 구성
            context_text = ""
            for i, art in enumerate(articles_data):
                # 상위 3개는 본문 전체, 나머지는 요약본만 제공 (토큰 절약 및 속도)
                content = art.get('full_text', art['description']) 
                context_text += f"[{i+1}] 언론사: {art['source']} | 제목: {art['title']}\n내용: {content[:1000]}\n\n"

            prompt = f"""
            당신은 정치/사회 이슈 전문 분석가입니다.
            사용자가 요청한 검색어: "{query}"
            
            아래 제공된 {len(articles_data)}개의 뉴스 기사들을 종합적으로 분석하여 '이슈 브리핑 보고서'를 작성해주세요.
            
            [분석 지침]
            1. 특정 언론사의 시각에 치우치지 말고, 중립적인 입장에서 서술하십시오.
            2. 논란이 있는 이슈라면 '찬성/반대' 또는 '여당/야당/정부'의 입장을 구분하여 정리하십시오.
            3. 가장 중요한 핵심 흐름을 3문단 이내로 요약하십시오.

            [입력 데이터]
            {context_text}

            [출력 형식 (JSON)]
            {{
                "summary_content": "종합적인 요약 내용 (마크다운 형식 가능, 줄바꿈은 \\n)",
                "keywords": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"]
            }}
            """
            
            response = model.generate_content(prompt)
            clean_text = response.text.strip().replace("```json", "").replace("```", "")
            return json.loads(clean_text)
            
        except Exception as e:
            print(f"⚠️ 브리핑 생성 실패: {e}")
            return None

    def clean_text(self, text):
        """ HTML 태그 제거 및 엔티티(&quot; 등) 변환 """
        if not text: return ""
        
        # 1. HTML 태그 제거 (<b>, </b> 등)
        clean = re.sub(r'<[^>]+>', '', text)
        
        # 2. HTML 엔티티 변환 (&quot; -> ", &lt; -> < 등)
        clean = html.unescape(clean)
        
        return clean

    def get_press_name(self, link, original_link):
        """ URL에서 언론사 이름을 찾아내는 함수 """
        # 주요 언론사 도메인 매핑 테이블
        PRESS_MAP = {
            "chosun.com": "조선일보", "hani.co.kr": "한겨레", "yna.co.kr": "연합뉴스",
            "khan.co.kr": "경향신문", "donga.com": "동아일보", "joongang.co.kr": "중앙일보",
            "kbs.co.kr": "KBS", "imbc.com": "MBC", "sbs.co.kr": "SBS", "jtbc": "JTBC",
            "mk.co.kr": "매일경제", "hankyung.com": "한국경제", "edaily.co.kr": "이데일리",
            "mt.co.kr": "머니투데이", "newsis.com": "뉴시스", "news1.kr": "뉴스1",
            "kmib.co.kr": "국민일보", "seoul.co.kr": "서울신문", "segye.com": "세계일보",
            "munhwa.com": "문화일보", "etnews.com": "전자신문", "zdnet.co.kr": "ZDNet",
            "nocutnews.co.kr": "노컷뉴스", "ohmynews.com": "오마이뉴스", "pressian.com": "프레시안",
            "dailian.co.kr": "데일리안", "inews24.com": "아이뉴스24", "fnnews.com": "파이낸셜뉴스"
        }

        target_url = original_link if original_link else link
        
        for domain, name in PRESS_MAP.items():
            if domain in target_url:
                return name
        
        return "기타 언론사" # 매핑 리스트에 없는 경우

    def run(self, user_query):
        print(f"🔍 '{user_query}' 관련 기사 수집 중...")
        
        # 1. 검색 (15개 가져옴)
        items = self.search_naver(user_query, display=15)
        if not items: 
            print("❌ 네이버 검색 결과가 없습니다.")
            return {"success": False}

        processed_articles = []
        source_counter = Counter()

        # 2. 데이터 가공 (상위 3개만 Deep Dive)
        for idx, item in enumerate(items):
            # 언론사명 파싱
            press_name = self.get_press_name(item['link'], item.get('originallink'))

            art_data = {
                "title": self.clean_text(item['title']),
                "link": item['link'],
                "description": self.clean_text(item['description']),
                "pubDate": item['pubDate'],
                "source": press_name
            }

            # 상위 3개는 본문 긁어오기
            if idx < 3:
                full_text = self.fetch_full_content(item['link'])
                if full_text:
                    art_data['full_text'] = full_text
            
            processed_articles.append(art_data)
            source_counter[press_name] += 1

        # 3. 종합 브리핑 생성
        print("🤖 AI 분석가가 보고서를 작성 중입니다...")
        briefing = self.generate_briefing(user_query, processed_articles)
        
        # 브리핑 실패 시 예외 처리
        if not briefing:
             return {
                "success": False,
                "message": "AI 브리핑 생성에 실패했습니다."
            }

        # 4. Response Body 구성
        final_keywords = briefing.get('keywords', [])
        
        # 기사 리스트 포맷팅
        formatted_articles = []
        for idx, art in enumerate(processed_articles):
            # 매칭 키워드 확인
            matched = [k for k in final_keywords if k in art['title'] or k in art['description']]
            
            formatted_articles.append({
                "id": f"news_{idx+1:03d}",
                "title": art['title'],
                "source": art['source'],
                "description": art['description'],
                "link": art['link'],
                "pubDate": art['pubDate'],
                "relevance_score": 0.0, # 네이버 API는 점수를 안주므로 기본값 처리 (필요시 계산 로직 추가)
                "matching_keywords": matched
            })

        return {
            "success": True,
            "data": {
                "original_query": user_query,
                "generated_keywords": final_keywords,
                "ai_summary": briefing.get('summary_content', ''),
                "total_results": len(formatted_articles),
                "articles": formatted_articles,
                "by_source": dict(source_counter)
            }
        }

# ==========================================
# 실행
# ==========================================
if __name__ == "__main__":
    agent = NewsBriefingAgent()
    result = agent.run("이재명 대통령 기자회견")
    print(json.dumps(result, indent=2, ensure_ascii=False))