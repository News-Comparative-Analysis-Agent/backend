import requests
from bs4 import BeautifulSoup
import json

url = 'https://n.news.naver.com/mnews/article/023/0003882767'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
res = requests.get(url, headers=headers)
soup = BeautifulSoup(res.text, 'html.parser')

img_tag1 = soup.find('meta', property='og:image')
img_tag2 = soup.select_one('meta[property="og:image"]')

print("Status:", res.status_code)
print("find:", img_tag1['content'] if img_tag1 else 'Not found')
print("select_one:", img_tag2['content'] if img_tag2 else 'Not found')
