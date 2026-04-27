# -*- coding: utf-8 -*-
import sys
import os
import asyncio
import aiohttp
import random
from collections import Counter
from bs4 import BeautifulSoup

# Force UTF-8 output for terminal
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(BASE_DIR)

# ---- Config ----
TARGET_PRESS_DICT = {
    "한겨레": "028", "경향신문": "032",
    "조선일보": "023", "동아일보": "020", "중앙일보": "025", "문화일보": "021",
    "한국일보": "469", "국민일보": "005", "서울신문": "081", "세계일보": "022"
}

DATE_LIST = ["20260425", "20260426"]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
EDITORIAL_SECTIONS = {"오피니언", "사설", "칼럼", "opinion", "editorial", "社說"}

# Scout.py's new filter
EDITORIAL_TITLE_KEYWORDS = [
    "[사설]", "사설]", "[社說]", "社說]"
]

# Semaphore to limit concurrency
sem = asyncio.Semaphore(5)

async def fetch_html(session, url):
    async with sem:
        await asyncio.sleep(random.uniform(0.5, 1.0))
        try:
            async with session.get(url, headers=HEADERS, timeout=15) as resp:
                if resp.status == 200:
                    return await resp.text(errors='replace')
                else:
                    print(f"  [ERR] {url} Status: {resp.status}")
        except Exception as e:
            print(f"  [ERR] {url}: {e}")
        return None

async def parse_article(session, link, title, press_name):
    html = await fetch_html(session, link)
    if not html: return None
    soup = BeautifulSoup(html, 'lxml')
    
    # Section
    section = ""
    meta = soup.select_one('meta[property="article:section"]')
    if meta: section = meta.get('content', '')
    else:
        cat = soup.select_one('.media_end_categorize_item')
        if cat: section = cat.get_text(strip=True)
    
    is_ed_sec = any(s in section for s in EDITORIAL_SECTIONS) if section else False
    is_ed_title = any(kw in title for kw in EDITORIAL_TITLE_KEYWORDS)
    
    return {
        "press": press_name, 
        "title": title, 
        "section": section, 
        "is_ed_sec": is_ed_sec, 
        "is_ed_title": is_ed_title,
        "collected": is_ed_title  # Only title keywords now
    }

async def crawl_lpod(session, press_name, oid, date_str):
    url = f"https://news.naver.com/main/list.naver?mode=LPOD&mid=sec&oid={oid}&listType=title&date={date_str}&page=1&sid1=110"
    html = await fetch_html(session, url)
    if not html: return []
    
    soup = BeautifulSoup(html, 'lxml')
    items = soup.select('.list_body li a')
    
    tasks = []
    seen = set()
    for item in items:
        link = item.get('href')
        if not link or link in seen or "article" not in link: continue
        seen.add(link)
        title = item.get_text(strip=True)
        if title:
            tasks.append(parse_article(session, link, title, press_name))
    
    if not tasks: return []
    return await asyncio.gather(*tasks)

async def main():
    print(f"Checking filter level for {DATE_LIST} (Opinion LPOD)", flush=True)
    async with aiohttp.ClientSession() as session:
        all_results = []
        for date_str in DATE_LIST:
            tasks = [crawl_lpod(session, name, oid, date_str) for name, oid in TARGET_PRESS_DICT.items()]
            batches = await asyncio.gather(*tasks)
            for b in batches: all_results.extend([r for r in b if r])
            
    print(f"\nTotal items scanned: {len(all_results)}", flush=True)
    collected = [r for r in all_results if r['collected']]
    filtered = [r for r in all_results if not r['collected']]
    
    print(f"Collected (Pass filter): {len(collected)}", flush=True)
    print(f"Filtered out: {len(filtered)}", flush=True)
    
    print("\n--- SAMPLE: COLLECTED ARTICLES ---", flush=True)
    for r in collected[:30]:
        reason = "SEC" if r['is_ed_sec'] else ""
        reason += " TITLE" if r['is_ed_title'] else ""
        print(f"  [{reason}] {r['press']} | {r['section']} | {r['title'][:60]}", flush=True)

    print("\n--- SAMPLE: FILTERED OUT (Mostly columns) ---", flush=True)
    for r in filtered[:30]:
        print(f"  [SKIP] {r['press']} | {r['section']} | {r['title'][:60]}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
