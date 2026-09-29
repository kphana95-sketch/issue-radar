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

client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = 'gemini-3.8-flash'

# 1. 경쟁사 실시간 랭킹 뉴스 크롤링
def fetch_target_news():
    url = "https://news.naver.com/main/ranking/popularDay.naver"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    # 모니터링 지정 경쟁사
    target_press_list = ['연합뉴스', '조선일보', '중앙일보', '매일경제', '아시아경제', '서울경제']
    collected = []
    
    ranking_boxes = soup.select('.rankingnews_box')
    for box in ranking_boxes:
        press_elem = box.select_one('.rankingnews_name')
        press_name = press_elem.get_text(strip=True) if press_elem else ""
        
        # 한국경제 제외 및 타깃 언론사만 수집
        if "한국경제" in press_name or press_name not in target_press_list:
            continue
            
        news_items = box.select('.rankingnews_list > li')
        for item in news_items[:5]:  # 언론사별 상위 5개씩 수집
            title_elem = item.select_one('.list_content > a') or item.select_one('a')
            if title_elem:
                title = title_elem.get_text(strip=True)
                if title:
                    collected.append(f"[{press_name}] {title}")
                    
    return collected

print("1. 경쟁사 랭킹 기사 수집 중...")
news_list = fetch_target_news()
print(f"-> 총 {len(news_list)}개 타사 기사 수집 완료!")
news_context = "\n".join(news_list)

# 2. 제미나이 데스킹 프롬프트 (한경 온라인 당직 에디터 맞춤 선별 기준)
prompt = f"""
당신은 한국경제신문 디지털뉴스룸의 실시간 이슈 모니터링 당직 데스크입니다.
수집된 경쟁사 인기 랭킹 기사 목록에서, 당직 근무 시간대에 온라인 트래픽을 견인할 수 있는 [실시간 화제 이슈 TOP 5]를 선별하고 발제 앵글을 브리핑하세요.

[선별 및 배제 기준 (철저 준수)]
1. 배제 대상 (절대 선별 금지):
   - 딱딱한 여야 정치 공방, 정쟁, 정부 관료 단순 발언.
   - 거시 지표 중심의 딱딱한 경제/금융 분석 기사.
   - 트럼프 관세 발언, 정상회담 등 일반적인 거시 국제 정치 뉴스.
   - 단순 연예인 결혼, 열애, 결별, 단순 드라마·예능 출연 홍보 기사.
2. 적극 선별 대상 (트래픽 및 명분 중심):
   - [사회/사건사고]: 온라인 공분을 일으키는 갑질, 황당 사고, 논란의 현장, 사기 수법 등 화제성 르포.
   - [생활/소비/문화]: 밥상 물가, SNS 유행 아이템, 직장인 공감 트렌드, 황당 민원.
   - [국제 토픽]: 정치 외교가 아닌 글로벌 바이럴 토픽(기상천외한 해외 사건·사고, 글로벌 진기명기 등).
   - [명분 있는 연예 이슈]: 
     * 부동산 명분: 연예인의 꼬마빌딩·아파트 매입 및 시세차익 이슈.
     * 산업/유통 명분: 특정 연예인 착장 품절 대란, 패션·뷰티 완판 현상.
     * 사회/법조 명분: 연예인 음주운전, 학폭, 사기, 전속계약 분쟁 등 사회적 구설수.

[수집된 경쟁사 랭킹 뉴스 목록]
{news_context}

[출력 양식]
■ [당직 실시간 이슈 레이더 TOP 5]

01. [이슈 타이틀]
- 기사 유형: (사회사건사고 / 명분있는연예 / 생활문화트렌드 / 해외토픽 중 택1)
- 타사 보도 현황: (어느 매체에서 다루고 있는지)
- 화제 및 클릭 유입 포인트: (독자들이 왜 이 기사에 열광/분노하는지)
- 한경 온라인 발제 앵글: (우리가 기사화할 때 살려야 할 명분과 차별화 팁)

(02번~05번 동일 형식으로 작성)

---
■ [당직 데스크의 트래픽 한 줄 팁]
(현재 포털 독자들의 관심 흐름과 주의사항 요약)
"""

# 3. 제미나이 호출 (5단계 지수 백오프 적용)
print("2. 제미나이 이슈 분석 진행 중...")
result_text = None
max_retries = 5

for attempt in range(1, max_retries + 1):
    try:
        print(f"-> {MODEL_NAME} 호출 시도 ({attempt}/{max_retries})...")
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )
        if response and response.text:
            result_text = response.text
            print("-> 제미나이 이슈 분석 완료!")
            break
    except Exception as e:
        wait_seconds = attempt * 5  # 5초, 10초, 15초, 20초, 25초 순차 대기
        print(f"경고: {attempt}차 시도 오류 ({e}). {wait_seconds}초 후 재시도합니다.")
        time.sleep(wait_seconds)

if not result_text:
    raise RuntimeError("구글 서버 과부하가 지속되어 요청을 완료하지 못했습니다. 잠시 후 다시 실행해 주세요.")

print("\n--- [분석 결과 요약] ---")
print(result_text[:400] + "...\n")

# 4. 이메일 자동 발송
def send_email(subject, body_text):
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    msg['Subject'] = subject
    msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
    
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    clean_pw = APP_PASSWORD.replace(" ", "") if APP_PASSWORD else ""
    server.login(SENDER_EMAIL, clean_pw)
    server.send_message(msg)
    server.quit()
    print("🎉 이메일 브리핑 발송 완료!")

now_str = (datetime.utcnow() + timedelta(hours=9)).strftime("%m월 %d일 %H시")
mail_title = f"[{now_str} 당직 이슈 레이더] 타사 랭킹 핫이슈 TOP 5 및 한경 발제 앵글"
send_email(mail_title, result_text)
