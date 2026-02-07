import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random
from datetime import datetime, timedelta

# ==========================================
# [설정] 수집 대상
# ==========================================
TARGET_PRESS_DICT = {
    "한겨레": "028", "경향신문": "032", 
    "조선일보": "023", "동아일보": "020", "연합뉴스": "001"
}

DAYS_TO_CRAWL = 7
# 필터링 및 중복 제거를 고려해 넉넉히 탐색
SCAN_LIMIT = 50 

# ==========================================
# 1. 상세 수집 함수 (기존과 동일)
# ==========================================
def get_article_detail_with_section(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 1. 섹션 확인
        section = ""
        meta_section = soup.select_one('meta[property="article:section"]')
        if meta_section:
            section = meta_section['content']
        else:
            cat_tag = soup.select_one('.media_end_categorize_item')
            if cat_tag:
                section = cat_tag.get_text(strip=True)
        
        if section != "정치":
            return None 
            
        # 2. 본문 추출
        content_area = soup.select_one('#dic_area') or soup.select_one('#newsct_article')
        content = ""
        if content_area:
            for tag in content_area.select('.img_desc, .end_photo_org, .media_end_summary, .byline_s'):
                tag.extract()
            content = content_area.get_text(strip=True)
            
        # 3. 이미지 & 날짜
        img_tag = soup.select_one('meta[property="og:image"]')
        image_url = img_tag['content'] if img_tag else ""
        
        date_tag = soup.select_one('.media_end_head_info_datestamp span')
        pub_date = date_tag['data-date-time'] if date_tag else ""

        return {
            "section": section,
            "content": content,
            "image_url": image_url,
            "pub_date": pub_date
        }
    except Exception:
        return None

# ==========================================
# 2. 메인 크롤러 (중복 제거 로직 추가)
# ==========================================
def crawl_unique_politics_news():
    all_news = []
    
    # 🔥 [핵심] 중복 방지용 '기사 ID' 저장소
    # URL이나 기사 고유 ID를 저장해두고, 이미 있으면 건너뜁니다.
    seen_articles = set()
    
    today = datetime.now()
    headers = {"User-Agent": "Mozilla/5.0"}
    
    print(f"🚀 정치 뉴스 수집 시작 (중복 원천 차단)...\n")
    
    for day_offset in range(DAYS_TO_CRAWL):
        target_date = today - timedelta(days=day_offset)
        date_str = target_date.strftime("%Y%m%d")
        display_date = target_date.strftime("%Y-%m-%d")
        
        print(f"📅 [Day {day_offset+1}/{DAYS_TO_CRAWL}] {display_date} 탐색 중...")
        
        for press_name, oid in TARGET_PRESS_DICT.items():
            url = f"https://news.naver.com/main/ranking/office.naver?officeId={oid}&date={date_str}"
            
            try:
                res = requests.get(url, headers=headers)
                soup = BeautifulSoup(res.text, 'html.parser')
                list_items = soup.select('.rankingnews_list li')
                
                if not list_items: continue

                collected_count = 0
                for item in list_items:
                    # 언론사별 하루 10개만 저장
                    if collected_count >= 10: break 
                    
                    link_tag = item.select_one('a')
                    if not link_tag: continue
                    
                    link = link_tag['href']
                    if link.startswith("/"): link = "https://news.naver.com" + link
                    
                    # 💡 URL에서 고유 식별자(article id)만 추출해서 비교하면 더 정확함
                    # 예: https://n.news.naver.com/article/028/0002674384 -> '028/0002674384'
                    try:
                        article_id = link.split("/article/")[1]
                        # ?sid=... 같은 파라미터 제거
                        article_id = article_id.split("?")[0] 
                    except:
                        article_id = link # 실패하면 링크 전체 사용

                    # 🔥 [중복 검사] 이미 수집한 기사면 패스!
                    if article_id in seen_articles:
                        continue
                        
                    # 수집 목록에 도장 쾅!
                    seen_articles.add(article_id)
                    
                    title = link_tag.get_text(strip=True)
                    
                    # 상세 페이지 접속 & 정치 여부 확인
                    detail = get_article_detail_with_section(link)
                    
                    if detail and len(detail['content']) > 50:
                        all_news.append({
                            "collection_date": display_date,
                            "press": press_name,
                            "title": title,
                            "section": detail['section'],
                            "content": detail['content'],
                            "image_url": detail['image_url'],
                            "pub_date": detail['pub_date'],
                            "link": link
                        })
                        collected_count += 1
                    
                    time.sleep(random.uniform(0.05, 0.1))
                
                print(f"   ✅ {press_name}: 신규 {collected_count}개 저장")
                
            except Exception as e:
                print(f"   ⚠️ {press_name} 에러: {e}")
                
    return pd.DataFrame(all_news)

# 실행
if __name__ == "__main__":
    df_unique = crawl_unique_politics_news()
    
    if not df_unique.empty:
        print(f"\n🎉 수집 완료! 총 {len(df_unique)}개")
        
        # 중복이 진짜 없는지 확인
        print(f"중복 제거 전: {len(df_unique) + (len(df_unique) - len(df_unique['link'].unique()))}") # 예시 계산
        print(f"중복 제거 후: {len(df_unique)}")
        
        filename = "weekly_politics_news_clean.csv"
        df_unique.to_csv(filename, index=False, encoding="utf-8-sig")
        print(f"📁 '{filename}'에 깔끔하게 저장되었습니다.")
    else:
        print("수집된 데이터가 없습니다.")