import os
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from google import genai

# 환경변수 불러오기
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
APP_PASSWORD = os.environ.get("APP_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")

client = genai.Client(api_key=GEMINI_API_KEY)
HISTORY_FILE = "sent_history.txt"

# 0. 이전 발송 기사 히스토리 불러오기 (중복 발송 완전 배제)
def load_history():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_history(new_titles):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        for t in new_titles:
            f.write(t + "\n")

sent_history = load_history()

# 1. 경쟁사 실시간 랭킹 뉴스 크롤링 (한국경제 제외 + 이전 발송 기사 사전 필터링)
def fetch_target_news():
    url = "https://news.naver.com/main/ranking/popularDay.naver"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    target_press_list = ['연합뉴스', '조선일보', '중앙일보', '매일경제', '아시아경제', '서울경제']
    collected = []
    
    ranking_boxes = soup.select('.rankingnews_box')
    for box in ranking_boxes:
        press_elem = box.select_one('.rankingnews_name')
        press_name = press_elem.get_text(strip=True) if press_elem else ""
        
        if "한국경제" in press_name or press_name not in target_press_list:
            continue
            
        news_items = box.select('.rankingnews_list > li')
        # 15개를 채우기 위해 각 매체당 상위 5개씩 수집
        for item in news_items[:5]:
            title_elem = item.select_one('.list_content > a') or item.select_one('a')
            if title_elem:
                title = title_elem.get_text(strip=True)
                full_item_str = f"[{press_name}] {title}"
                # 이전 시간에 이미 보낸 기사이거나 이번 회차 중복 수집인 건 제외
                if title and (title not in sent_history) and (full_item_str not in collected):
                    collected.append(full_item_str)
                    
    return collected

print("1. 경쟁사 랭킹 기사 수집 중 (한국경제 제외 및 이전 발송 기사 필터링)...")
news_list = fetch_target_news()
print(f"-> 총 {len(news_list)}개 신규 타사 기사 수집 완료!")

if not news_list:
    print("새롭게 처리할 미발송 랭킹 기사가 없습니다. 종료합니다.")
    exit(0)

news_context = "\n".join(news_list)

# 2. 제미나이 데스킹 프롬프트 (따옴표 충돌 없는 안전한 삼중따옴표 블록)
prompt = f'''당신은 한국경제신문 디지털뉴스룸의 실시간 이슈 모니터링 당직 데스크입니다.
수집된 경쟁사 인기 랭킹 기사 목록에서, 당직 근무 시간대에 온라인 트래픽을 견인할 수 있는 [실시간 화제 이슈 TOP 15]를 선별하고 발제 앵글을 브리핑하세요.

[선별 및 배제 기준 (철저 준수)]
1. 배제 대상 (
