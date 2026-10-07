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
        # 15개를 채우기 위해 각 매체당 상위 5개씩 긁어옴
        for item in news_items[:5]:
            title_elem = item.select_one('.list_content > a') or item.select_one('a')
            if title_elem:
                title = title_elem.get_text(strip=True)
                # 이전 시간에 이미 보낸 기사 목록에 있거나 중복 수집된 건 제외
                if title and title not in sent_history and title not in collected:
                    collected.append(f"[{press_name}] {title}")
                    
    return collected

print("1. 경쟁사 랭킹 기사 수집 중 (한국경제 제외 및 이전 발송 기사 필터링)...")
news_list = fetch_target_news()
print(f"-> 총 {len(news_list)}개 신규 타사 기사 수집 완료!")

if not news_list:
    print("새롭게 처리할 미발송 랭킹 기사가 없습니다. 종료합니다.")
    exit(0)

news_context = "\n".join(news_list)

# 2. 제미나이 데스킹 프롬프트 (TOP 15 확대 + 우라까이 용이성 엄수 + 한경 발제 앵글)
prompt = f"""
당신은 한국경제신문 디지털뉴스룸의 실시간 이슈 모니터링 당직 데스크입니다.
수집된 경쟁사 인기 랭킹 기사 목록에서, 당직 기자나 에디터가 '5~10분 안에 빠르고 안전하게 재가공(우라까이)하여 즉시 출고해 포털 트래픽을 선점할 수 있는 실시간 화제 이슈 TOP 15'를 선별하고 발제 앵글을 브리핑하세요.

[선별 및 배제 기준 (철저 준수)]
1. 배제 대상 (절대 선별 금지):
   - 기자가 발로 뛴 [단독], [기획], [현장 르포], 심층 인터뷰 (타사 취재 노력이 들어간 기사는 재가공이 어렵고 저작권/엠바고 위험이 있으므로 즉시 탈락).
   - 딱딱한 여야 정치 공방, 정쟁, 정부 관료 단순 정치성 발언.
   - 거시 지표 중심의 딱딱한 경제/금융 분석 기사.
   - 트럼프 관세 발언, 정상회담 등 일반적인 거시 국제 정치 뉴스.
   - 단순 연예인 결혼, 열애, 결별, 단순 드라마·예능 출연 홍보 기사.
   - 법적 분쟁 소지가 크거나 사실 확인(크로스체크)이 필요한 폭로성 기사.
2. 적극 선별 대상 (트래픽 최상 + 5분 만에 재가공/우라까이 가능한 이슈 중심, 총 15개 선별):
   - [사회/사건사고]: 온라인 공분을 일으키는 갑질, 황당 사고, 논란의 현장, 사기 수법 등 화제성 르포 및 경찰/소방 공식 브리핑.
   - [생활/소비/문화]: 밥상 물가, SNS 유행 아이템, 직장인 공감 트렌드, 황당 민원, 통계청/한은/소비자원 공식 발표 자료.
   - [국제 토픽]: 정치 외교가 아닌 글로벌 바이럴 토픽(기상천외한 해외 사건·사고, 글로벌 진기명기, 외신 인용 기사).
   - [공식 발표/보도자료]: 대기업 신제품 출시, 공시, 지자체·공공기관 발표 (팩트가 명확해 5분 만에 뼈대 잡기 쉬운 기사).
   - [명분 있는 연예 이슈]:
     * 부동산 명분: 연예인의 꼬마빌딩·아파트 매입 및 시세차익 이슈.
     * 산업/유통 명분: 특정 연예인 착장 품절 대란, 패션·뷰티 완판 현상.
     * 사회/법조 명분: 연예인 음주운전, 학폭, 사기, 전속계약 분쟁 등 공적 구설수.

[수집된 경쟁사 랭킹 뉴스 목록]
{news_context}

[출력 양식]
■ [당직 실시간 이슈 레이더 TOP 15]

01. [이슈 타이틀]
- 기사 유형: (사회사건사고 / 명분있는연예 / 생활문화트렌드 / 해외토픽 / 보도자료 중 택1)
- 타사 보도 현황: (어느 매체에서 다루고 있는지)
- 화제 및 클릭 유입 포인트: (독자들이 왜 이 기사에 열광/분노하는지)
- 한경 온라인 발제 앵글 및 우라까이 팁: (우리가 기사화할 때 살려야 할 명분과 차별화 팁, 그리고 어떤 공식 발표/커뮤니티 소스를 참고해 5분 만에 쓸 수 있는지)

(02번부터 15번까지 동일 형식으로 15개 모두 작성)

---
■ [당직 데스크의 트래픽 한 줄 팁]
(현재 포털 독자들의 관심 흐름과 주의사항 요약)
"""

# 3. 실시간 동적 가용 모델 탐색 및 데스킹 호출
print("2. 제미나이 가용 모델 탐색 및 데스킹 진행 중...")

def get_dynamic_models():
    detected = []
    try:
        for m in client.models.list():
            name = m.name.replace("models/", "") if hasattr(m, 'name') else str(m)
            if "gemini" in name.lower() and not any(k in name.lower() for k in ['embedding', 'aqa', 'imagen', 'live']):
                detected.append(name)
    except Exception as e:
        print(f"모델 실시간 조회 실패, 기본 목록 사용: {e}")

    flash_models = [m for m in detected if "flash" in m.lower()]
    pro_models = [m for m in detected if "pro" in m.lower() and m not in flash_models]
    
    final_list = flash_models + pro_models
    fallback_defaults = ['gemini-3.8-flash', 'gemini-flash-latest', 'gemini-pro-latest']
    return list(dict.fromkeys(final_list + fallback_defaults))

models_to_try = get_dynamic_models()
result_text = None
max_retries_per_model = 3

for current_model in models_to_try:
    print(f"\n[모델 시도] '{current_model}' 호출 중...")
    model_success = False

    for attempt in range(1, max_retries_per_model + 1):
        try:
            chat = client.chats.create(model=current_model)
            response = chat.send_message(prompt)
            
            if response and response.text:
                result_text = response.text.strip()
                print(f"-> [{current_model}] 데스킹 성공!")
                model_success = True
                break
        except Exception as e:
            err_msg = str(e)
            if "404" in err_msg or "NOT_FOUND" in err_msg:
                print(f"   [{current_model}] 404 미지원 모델. 다음으로 넘어갑니다.")
                break
                
            if any(k in err_msg for k in ["503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED"]):
                wait_sec = attempt * 5
                print(f"   [{current_model}] ({attempt}/{max_retries_per_model}차) 일시 지연: {wait_sec}초 대기 후 재시도...")
                time.sleep(wait_sec)
            else:
                print(f"   [{current_model}] 처리 에러: {err_msg[:80]}...")
                break

    if model_success:
        break
    else:
        print(f"   ⚠️ [{current_model}] 응답 불가. 다음 후보 모델로 자동 전환합니다.")

if not result_text:
    raise RuntimeError("모든 가용 제미나이 모델 호출에 실패했습니다.")

print("\n--- [분석 결과 요약] ---")
print(result_text[:400] + "...\n")

# 4. 발송된 기사 히스토리 저장 (다음 시간대 중복 제외용)
newly_sent_titles = [item.split("] ", 1)[-1] for item in news_list if "] " in item]
save_history(newly_sent_titles)

# 5. 이메일 자동 발송
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

now_str = (datetime.utcnow() + timedelta(hours=9)).strftime("%m월 %d일 %H시 %M분")
mail_title = f"[{now_str} 당직 이슈 레이더] 타사 랭킹 핫이슈 TOP 15 및 한경 발제 앵글"
send_email(mail_title, result_text)
