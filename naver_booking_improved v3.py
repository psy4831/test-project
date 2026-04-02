import asyncio
import os
import smtplib
import logging
import calendar as cal_module
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, date
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# aiohttp 설치 필요: pip install aiohttp --break-system-packages
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    import requests
    HAS_AIOHTTP = False


# ====================================================
#  로깅 설정
# ====================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# ====================================================
#  설정값 - 여기만 수정하세요!
# ====================================================

MY_EMAIL     = "psy4831@gmail.com"
# ★ 보안: 반드시 환경변수 사용!
# 터미널에서 설정: export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
if not APP_PASSWORD:
    logger.warning("⚠️  GMAIL_APP_PASSWORD 환경변수가 설정되지 않았습니다!")
    logger.warning("    이메일 알림을 사용하려면 다음 명령어로 설정하세요:")
    logger.warning("    export GMAIL_APP_PASSWORD='your_app_password'")

ALERT_EMAIL  = "psy4831@gmail.com"

PERSON1 = {
    "name":     "배성연",
    "birthday": "19850810",
}
PERSON2 = {
    "name":     "윤성현",
    "birthday": "19850825",
}

# ★ 모니터링 대상 월
TARGET_YEAR   = 2026
TARGET_MONTHS = [4, 5]  # 4월, 5월 예약 감지

# ★ 모니터링 주기 (초)
CHECK_INTERVAL = 30

# ★ 타이밍 설정 (초) - 필요시 조정 가능
TIMING = {
    "page_load_wait": 2.0,
    "click_delay": 0.8,
    "form_fill_delay": 0.3,
    "month_navigation_delay": 0.6,
    "selector_timeout": 5000,  # 밀리초
    "form_timeout": 12000,      # 밀리초
}

BIZ_ID  = "1359557"
ITEM_ID = "6566444"

BOOKING_URL = (
    f"https://m.booking.naver.com/booking/13/bizes/{BIZ_ID}"
    f"/items/{ITEM_ID}?lang=ko&theme=place"
)

LOGIN_STATE_FILE = "naver_login.json"  # save_login.py로 미리 생성한 파일

MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

HEADERS = {
    "User-Agent": MOBILE_USER_AGENT,
    "Accept-Language": "ko-KR,ko;q=0.9",
}


# ====================================================
#  이메일 발송
# ====================================================
def send_email(subject: str, body: str) -> bool:
    """이메일 발송 (성공 여부 반환)"""
    if not APP_PASSWORD:
        logger.warning("이메일 전송 실패: APP_PASSWORD 미설정")
        return False
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = MY_EMAIL
    msg["To"]      = ALERT_EMAIL
    msg.attach(MIMEText(body, "plain", "utf-8"))
    
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(MY_EMAIL, APP_PASSWORD)
            server.send_message(msg)
        logger.info("✉️  이메일 전송 완료!")
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("⚠️  Gmail 인증 실패! APP_PASSWORD를 확인하세요.")
        return False
    except Exception as e:
        logger.error(f"⚠️  이메일 전송 실패: {type(e).__name__}: {e}")
        return False


# ====================================================
#  자리 감지 (비동기)
# ====================================================
async def check_availability() -> tuple[bool, int | None, str]:
    """
    각 월별로 예약 페이지를 확인하여 예약 가능 상태 감지.
    aiohttp 사용 권장 (없으면 requests fallback)
    """
    if HAS_AIOHTTP:
        return await _check_availability_async()
    else:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _check_availability_sync)


async def _check_availability_async() -> tuple[bool, int | None, str]:
    """aiohttp를 사용한 비동기 HTTP 체크"""
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for month in TARGET_MONTHS:
            check_url = (
                f"https://m.booking.naver.com/booking/13/bizes/{BIZ_ID}"
                f"/items/{ITEM_ID}?lang=ko&startDate={TARGET_YEAR}-{month:02d}-01&theme=place"
            )

            try:
                async with session.get(check_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    text = await resp.text()

                    # 로그인 필요 페이지 감지
                    if "로그인" in text and "예약하기" not in text:
                        logger.warning(f"[{month:02d}월] ⚠️  실패 원인: 로그인 필요 (HTTP 체크는 세션 없이 동작 - 결과 신뢰 불가)")
                        continue

                    if resp.status == 404 or "운영하지 않는" in text or "존재하지 않는" in text:
                        logger.warning(f"[{month:02d}월] ⚠️  실패 원인: 페이지 오류 (HTTP {resp.status}, 업체/상품 ID 확인 필요)")
                        continue

                    if resp.status != 200:
                        logger.warning(f"[{month:02d}월] ⚠️  실패 원인: HTTP {resp.status} 응답")
                        continue

                    available_keywords = ["예약하기", "잔여", "예약 가능", "남은 자리"]
                    full_keywords = ["마감", "예약불가", "예약 불가", "품절", "모두 예약됨"]

                    has_available = any(k in text for k in available_keywords)
                    has_full = any(k in text for k in full_keywords)

                    if has_available and not has_full:
                        message = f"{TARGET_YEAR}년 {month}월 예약 가능한 자리 발견!"
                        return True, month, message

                    if has_full:
                        logger.info(f"[{month:02d}월] ℹ️  실패 원인: 자리 없음 (마감/예약불가 상태)")
                    elif not has_available:
                        logger.info(f"[{month:02d}월] ℹ️  실패 원인: 예약 버튼 미감지 (페이지 구조 변경 또는 비공개 상태)")
                    else:
                        logger.info(f"[{month:02d}월] ℹ️  실패 원인: 예약 가능 + 마감 키워드 동시 감지 (상태 불명확)")

            except asyncio.TimeoutError:
                logger.warning(f"[{month:02d}월] ⚠️  실패 원인: 네트워크 타임아웃 (15초 초과)")
            except Exception as e:
                logger.warning(f"[{month:02d}월] ⚠️  실패 원인: 예외 발생 ({type(e).__name__}: {e})")

        return False, None, "자리 없음"


def _check_availability_sync() -> tuple[bool, int | None, str]:
    """requests를 사용한 동기 HTTP 체크 (fallback)"""
    for month in TARGET_MONTHS:
        check_url = (
            f"https://m.booking.naver.com/booking/13/bizes/{BIZ_ID}"
            f"/items/{ITEM_ID}?lang=ko&startDate={TARGET_YEAR}-{month:02d}-01&theme=place"
        )

        try:
            resp = requests.get(check_url, headers=HEADERS, timeout=15)
            text = resp.text

            # 로그인 필요 페이지 감지
            if "로그인" in text and "예약하기" not in text:
                logger.warning(f"[{month:02d}월] ⚠️  실패 원인: 로그인 필요 (HTTP 체크는 세션 없이 동작 - 결과 신뢰 불가)")
                continue

            if resp.status_code == 404 or "운영하지 않는" in text or "존재하지 않는" in text:
                logger.warning(f"[{month:02d}월] ⚠️  실패 원인: 페이지 오류 (HTTP {resp.status_code}, 업체/상품 ID 확인 필요)")
                continue

            if resp.status_code != 200:
                logger.warning(f"[{month:02d}월] ⚠️  실패 원인: HTTP {resp.status_code} 응답")
                continue

            available_keywords = ["예약하기", "잔여", "예약 가능", "남은 자리"]
            full_keywords = ["마감", "예약불가", "예약 불가", "품절", "모두 예약됨"]

            has_available = any(k in text for k in available_keywords)
            has_full = any(k in text for k in full_keywords)

            if has_available and not has_full:
                message = f"{TARGET_YEAR}년 {month}월 예약 가능한 자리 발견!"
                return True, month, message

            if has_full:
                logger.info(f"[{month:02d}월] ℹ️  실패 원인: 자리 없음 (마감/예약불가 상태)")
            elif not has_available:
                logger.info(f"[{month:02d}월] ℹ️  실패 원인: 예약 버튼 미감지 (페이지 구조 변경 또는 비공개 상태)")
            else:
                logger.info(f"[{month:02d}월] ℹ️  실패 원인: 예약 가능 + 마감 키워드 동시 감지 (상태 불명확)")

        except requests.Timeout:
            logger.warning(f"[{month:02d}월] ⚠️  실패 원인: 네트워크 타임아웃 (15초 초과)")
        except Exception as e:
            logger.warning(f"[{month:02d}월] ⚠️  실패 원인: 예외 발생 ({type(e).__name__}: {e})")

    return False, None, "자리 없음"


# ====================================================
#  달력 월 이동
# ====================================================
async def ensure_month_visible(page, year: int, month: int, max_clicks: int = 6) -> bool:
    """
    달력을 특정 월로 이동 (앞/뒤 양방향)
    """
    for attempt in range(max_clicks):
        try:
            month_text = await page.locator(
                "[class*='calendar_header'], [class*='month_title'], [class*='calendar_month']"
            ).first.inner_text(timeout=3000)

            if f"{month}월" in month_text or f"{month:02d}월" in month_text:
                logger.info(f"    ✅ {month}월 달력 확인됨")
                return True

            # 현재 달력 월 파싱하여 앞/뒤 방향 결정
            current_month = None
            for m in range(1, 13):
                if f"{m}월" in month_text:
                    current_month = m
                    break

            if current_month is not None and current_month > month:
                # 현재 월이 목표보다 크면 이전 달로 이동
                prev_btn = (
                    page.locator("button[aria-label*='이전']")
                    .or_(page.locator("button.btn_prev"))
                    .or_(page.locator("button:has-text('이전')"))
                    .first
                )
                if await prev_btn.count():
                    await prev_btn.click()
                    await asyncio.sleep(TIMING["month_navigation_delay"])
                    continue
                else:
                    logger.warning(f"    ⚠️  실패 원인: 이전 달 버튼을 찾을 수 없음 (현재 {current_month}월 → 목표 {month}월)")
                    return False
            else:
                # 다음 달로 이동
                next_btn = (
                    page.locator("button[aria-label*='다음']")
                    .or_(page.locator("button.btn_next"))
                    .or_(page.locator("button:has-text('다음')"))
                    .first
                )
                if await next_btn.count():
                    await next_btn.click()
                    await asyncio.sleep(TIMING["month_navigation_delay"])
                else:
                    logger.warning(f"    ⚠️  실패 원인: 다음 달 버튼을 찾을 수 없음")
                    return False

        except PlaywrightTimeout:
            if attempt == max_clicks - 1:
                logger.warning(f"    ⚠️  실패 원인: 달력 헤더 로드 타임아웃 ({max_clicks}회 시도 초과)")
        except Exception as e:
            if attempt == max_clicks - 1:
                logger.warning(f"    ⚠️  실패 원인: 달력 이동 중 예외 ({type(e).__name__}: {e})")
            continue

    logger.warning(f"    ⚠️  실패 원인: {max_clicks}회 시도 후에도 {month}월 달력 이동 실패")
    return False


# ====================================================
#  주말 날짜 계산
# ====================================================
def get_weekend_dates(year: int, month: int) -> list:
    """
    해당 월의 모든 주말(금, 토, 일) 날짜 반환
    """
    _, days_in_month = cal_module.monthrange(year, month)
    weekends = []
    for day in range(1, days_in_month + 1):
        weekday = date(year, month, day).weekday()  # 0=월, 4=금, 5=토, 6=일
        if weekday >= 4:  # 금요일 이상
            weekends.append(day)
    return weekends


# ====================================================
#  날짜 선택
# ====================================================
async def select_earliest_weekend(page, target_month: int) -> bool:
    """
    가장 빠른 주말 날짜 선택
    """
    weekend_days = get_weekend_dates(TARGET_YEAR, target_month)
    logger.info(f"    {target_month}월 주말: {weekend_days}")
    
    for day in weekend_days:
        target_date = f"{TARGET_YEAR}-{target_month:02d}-{day:02d}"
        
        # data-date 속성을 이용한 선택
        selectors = [
            f"button[data-date='{target_date}']:not(.is-disabled):not(.is-full)",
            f"button[data-date='{target_date}']:not([disabled])",
            f"td[data-date='{target_date}'] button:not(.is-disabled)",
        ]
        
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if await btn.count() and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(TIMING["click_delay"])

                    # 시간 슬롯이 실제로 나타났는지 확인 후 return
                    try:
                        await page.wait_for_selector(
                            "button.time_slot, button[class*='time']:not([disabled]), li.time_item button",
                            timeout=TIMING["selector_timeout"]
                        )
                        logger.info(f"    ✅ {target_date} 선택됨 (시간 슬롯 확인)")
                        return True
                    except PlaywrightTimeout:
                        logger.warning(f"    ⚠️  {target_date} 클릭 후 시간 슬롯 미표시 → 다음 날짜 시도")
                        continue  # 시간 슬롯이 없으면 다음 날짜로
            except Exception as e:
                logger.debug(f"    셀렉터 {sel} 실패: {type(e).__name__}")
                continue
        
        # data-date 속성이 없는 경우 텍스트 기반 fallback
        try:
            calendar_btn = page.locator(
                "button.calendar_day:not(.is-disabled):not(.is-full)"
            ).filter(has_text=str(day)).first
            if await calendar_btn.count() and await calendar_btn.is_visible():
                await calendar_btn.click()
                await asyncio.sleep(TIMING["click_delay"])

                try:
                    await page.wait_for_selector(
                        "button.time_slot, button[class*='time']:not([disabled]), li.time_item button",
                        timeout=TIMING["selector_timeout"]
                    )
                    logger.info(f"    ✅ {target_date} 선택됨 (텍스트 fallback, 시간 슬롯 확인)")
                    return True
                except PlaywrightTimeout:
                    logger.warning(f"    ⚠️  {target_date} 텍스트 fallback 클릭 후 시간 슬롯 미표시 → 다음 날짜 시도")
        except Exception as e:
            logger.debug(f"    텍스트 fallback 실패: {type(e).__name__}")
    
    logger.warning(f"    ⚠️  실패 원인: {target_month}월 주말 날짜 중 예약 가능하고 시간 슬롯이 있는 날짜 없음")
    return False


# ====================================================
#  시간 선택
# ====================================================
async def select_earliest_time(page) -> bool:
    """
    가장 빠른 시간 슬롯 선택
    """
    selectors = [
        "button.time_slot:not(.is-disabled):not(.is-full)",
        "button[class*='time']:not(.disabled):not(.full):not([disabled])",
        "li.time_item:not(.is-disabled) button",
        "div[class*='time'] button:not(.disabled):not(.full)",
    ]
    
    for sel in selectors:
        try:
            slot = page.locator(sel).first
            if await slot.count() and await slot.is_visible():
                slot_text = await slot.inner_text()
                await slot.click()
                await asyncio.sleep(TIMING["click_delay"])
                logger.info(f"    ✅ 시간 슬롯 선택: {slot_text.strip()}")
                return True
        except Exception as e:
            logger.debug(f"    시간 셀렉터 {sel} 실패: {type(e).__name__}")
            continue
    
    logger.warning("    ⚠️  실패 원인: 가능한 시간 슬롯 없음 (모두 마감 또는 셀렉터 불일치)")
    return False


# ====================================================
#  예약자 정보 입력
# ====================================================
async def fill_person_info(page, p1: dict, p2: dict):
    """
    예약자 정보 (이름, 생년월일) 입력
    """
    # ── 이름 필드 찾기 ──
    name_loc = page.locator(
        "input[name='name'], "
        "input[placeholder*='이름'], "
        "input[placeholder*='성함'], "
        "input[placeholder*='배우자'], "
        "input[placeholder*='동반자'], "
        "input[placeholder*='게스트']"
    )
    name_count = await name_loc.count()
    
    if name_count >= 1:
        await name_loc.nth(0).fill(p1["name"])
        await asyncio.sleep(TIMING["form_fill_delay"])
        logger.info(f"    ✅ 본인 이름: {p1['name']}")
    
    if name_count >= 2:
        await name_loc.nth(1).fill(p2["name"])
        await asyncio.sleep(TIMING["form_fill_delay"])
        logger.info(f"    ✅ 배우자 이름: {p2['name']}")
    else:
        # name_count == 1이면 배우자 전용 필드 별도 탐색
        spouse_loc = page.locator(
            "input[name*='spouse'], input[name*='partner'], "
            "input[name*='companion'], input[name*='guest'], "
            "input[placeholder*='배우자']"
        )
        if await spouse_loc.count():
            await spouse_loc.first.fill(p2["name"])
            await asyncio.sleep(TIMING["form_fill_delay"])
            logger.info(f"    ✅ 배우자 이름 (별도 필드): {p2['name']}")
    
    # ── 생년월일 필드 찾기 ──
    birth_loc = page.locator(
        "input[name='birth'], "
        "input[name='birthday'], "
        "input[placeholder*='생년월일'], "
        "input[placeholder*='생일'], "
        "input[placeholder*='YYYYMMDD'], "
        "input[placeholder*='yyyymmdd']"
    )
    birth_count = await birth_loc.count()
    
    if birth_count >= 1:
        await birth_loc.nth(0).fill(p1["birthday"])
        await asyncio.sleep(TIMING["form_fill_delay"])
        logger.info(f"    ✅ 본인 생년월일: {p1['birthday']}")
    
    if birth_count >= 2:
        await birth_loc.nth(1).fill(p2["birthday"])
        await asyncio.sleep(TIMING["form_fill_delay"])
        logger.info(f"    ✅ 배우자 생년월일: {p2['birthday']}")
    else:
        spouse_birth_loc = page.locator(
            "input[name*='spouse_birth'], input[name*='partner_birth'], "
            "input[name*='companion_birth'], input[name*='guest_birth'], "
            "input[placeholder*='배우자 생년월일'], input[placeholder*='동반자 생년월일']"
        )
        if await spouse_birth_loc.count():
            await spouse_birth_loc.first.fill(p2["birthday"])
            await asyncio.sleep(TIMING["form_fill_delay"])
            logger.info(f"    ✅ 배우자 생년월일 (별도 필드): {p2['birthday']}")
        else:
            logger.warning(f"    ⚠️  실패 원인: 배우자 생년월일 입력 필드를 찾을 수 없음 (폼 구조 확인 필요)")


# ====================================================
#  예약 핵심 로직
# ====================================================
async def run_booking(page, target_month: int) -> bool:
    """
    예약 수행 메인 로직
    """
    # 1단계: 월 확인
    logger.info(f"    [1/6] 달력을 {target_month}월로 이동...")
    month_ok = await ensure_month_visible(page, TARGET_YEAR, target_month)
    if not month_ok:
        logger.warning(f"    ⚠️  {target_month}월 이동 실패")
    
    # 2단계: 날짜 선택
    logger.info(f"    [2/6] 주말 날짜 선택...")
    date_ok = await select_earliest_weekend(page, target_month)
    if not date_ok:
        raise Exception(f"{target_month}월 가능한 주말 없음")
    
    # 3단계: 시간 선택
    logger.info(f"    [3/6] 시간 슬롯 선택...")
    time_ok = await select_earliest_time(page)
    if not time_ok:
        raise Exception("가능한 시간 슬롯 없음")
    
    # 4단계: 예약하기 버튼 클릭
    logger.info(f"    [4/6] '예약하기' 버튼 클릭...")
    booking_btn = (
        page.locator("button:has-text('예약하기')")
        .or_(page.locator("button:has-text('신청하기')"))
        .or_(page.locator("button:has-text('바로 예약')"))
        .or_(page.locator("button:has-text('예약 신청')"))
        .first
    )
    
    try:
        await booking_btn.click()
        await asyncio.sleep(TIMING["page_load_wait"])
    except Exception as e:
        raise Exception(f"예약하기 버튼 클릭 실패: {type(e).__name__}: {e}")
    
    # 5단계: 예약자 정보 입력
    logger.info(f"    [5/6] 예약자 정보 폼 로드 대기...")
    try:
        await page.wait_for_selector(
            "input[name='name'], input[placeholder*='이름'], "
            "input[placeholder*='생년월일']",
            timeout=TIMING["form_timeout"]
        )
    except PlaywrightTimeout:
        logger.warning(f"    ⚠️  폼 셀렉터 미감지 → 3초 추가 대기")
        await asyncio.sleep(3)
    
    await fill_person_info(page, PERSON1, PERSON2)
    await asyncio.sleep(1)
    
    # 6단계: 예약 확인 버튼 클릭
    logger.info(f"    [6/6] '예약 확인' 버튼 클릭...")
    confirm_btn = (
        page.locator("button:has-text('예약 확인')")
        .or_(page.locator("button:has-text('예약확인')"))
        .or_(page.locator("button:has-text('예약 완료')"))
        .or_(page.locator("button:has-text('예약완료')"))
        .or_(page.locator("button:has-text('신청하기')"))
        .or_(page.locator("button:has-text('결제하기')"))
        .or_(page.locator("form button:has-text('확인')"))
        .first
    )
    
    try:
        await confirm_btn.click()
        await asyncio.sleep(3)
    except Exception as e:
        raise Exception(f"예약 확인 버튼 클릭 실패: {type(e).__name__}: {e}")
    
    # 결과 확인
    content = await page.content()
    success = any(kw in content for kw in ["예약이 완료", "예약완료", "접수되었", "신청이 완료"])
    return success


# ====================================================
#  자동 예약 실행 (Playwright 사용)
# ====================================================
async def do_booking(target_month: int) -> bool:
    """
    저장된 로그인 세션을 사용하여 예약 수행
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, slow_mo=100)
        
        try:
            context = await browser.new_context(
                storage_state=LOGIN_STATE_FILE,
                viewport={"width": 390, "height": 844},
                user_agent=MOBILE_USER_AGENT,
            )
        except FileNotFoundError:
            logger.error(f"❌ 로그인 세션 파일 '{LOGIN_STATE_FILE}' 없음!")
            logger.info(f"💡  먼저 save_login.py로 세션을 저장하세요.")
            await browser.close()
            raise Exception(f"로그인 세션 파일 '{LOGIN_STATE_FILE}' 없음")
        
        page = await context.new_page()
        
        try:
            logger.info(f"\n  📱 예약 페이지 로드 중...")
            await page.goto(BOOKING_URL, wait_until="domcontentloaded")
            await asyncio.sleep(TIMING["page_load_wait"])
            
            success = await run_booking(page, target_month)
            
            if success:
                logger.info(f"\n  ★★★ {target_month}월 예약 완료! ★★★")
                screenshot_path = f"booking_success_{target_month}.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                logger.info(f"  📸 스크린샷 저장: {screenshot_path}")
                
                send_email(
                    f"[네이버 예약] {target_month}월 자동 예약 완료! 🎉",
                    f"예약이 성공적으로 완료되었습니다!\n\n"
                    f"예약 월: {target_month}월\n"
                    f"예약자1 (본인)  : {PERSON1['name']} ({PERSON1['birthday']})\n"
                    f"예약자2 (배우자): {PERSON2['name']} ({PERSON2['birthday']})\n\n"
                    f"예약 확인: {BOOKING_URL}",
                )
                return True
            else:
                logger.warning(f"\n  ⚠️  {target_month}월 결과 확인 불가 → 수동 확인 필요")
                screenshot_path = f"booking_result_{target_month}.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                logger.info(f"  📸 스크린샷 저장: {screenshot_path}")
                
                send_email(
                    f"[네이버 예약] {target_month}월 수동 확인 필요",
                    f"예약 시도했으나 완료 여부 불확실.\n\n"
                    f"{screenshot_path} 스크린샷을 확인하세요.\n\n"
                    f"예약 페이지: {BOOKING_URL}",
                )
                return False
        
        except Exception as e:
            logger.error(f"\n  ❌ {target_month}월 예약 오류: {type(e).__name__}: {e}")
            screenshot_path = f"booking_error_{target_month}.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            logger.info(f"  📸 스크린샷 저장: {screenshot_path}")
            
            send_email(
                f"[네이버 예약] {target_month}월 자동 예약 실패",
                f"오류 메시지: {e}\n\n"
                f"수동 예약:\n{BOOKING_URL}",
            )
            raise
        
        finally:
            await asyncio.sleep(2)
            await browser.close()


# ====================================================
#  메인 모니터링 루프
# ====================================================
async def main():
    logger.info("=" * 70)
    logger.info(" 🚀 네이버 예약 모니터링 시스템 (4-5월)")
    logger.info("=" * 70)
    logger.info(f" 📅 대상 월: {TARGET_YEAR}년 {TARGET_MONTHS}월")
    logger.info(f" ⏱️  확인 주기: {CHECK_INTERVAL}초")
    logger.info(f" 📧 알림 이메일: {ALERT_EMAIL}")
    logger.info(f" 📝 예약자1 (본인)  : {PERSON1['name']} ({PERSON1['birthday']})")
    logger.info(f" 👨‍👩‍👧 예약자2 (배우자): {PERSON2['name']} ({PERSON2['birthday']})")
    logger.info(f" 📂 로그인 세션: {LOGIN_STATE_FILE}")
    
    if HAS_AIOHTTP:
        logger.info(f" 🌐 HTTP 클라이언트: aiohttp (비동기)")
    else:
        logger.info(f" 🌐 HTTP 클라이언트: requests (동기 fallback)")
        logger.info(f" 💡  aiohttp 설치 권장: pip install aiohttp --break-system-packages")
    
    logger.info("=" * 70)
    logger.info("")
    
    booking_done = False
    alerted_months: set[int] = set()
    check_count = 0
    
    while not booking_done:
        check_count += 1
        logger.info(f"[확인 #{check_count}] 예약 가능 여부 확인 중...")
        
        try:
            found, target_month, message = await check_availability()
        except Exception as e:
            logger.error(f"확인 중 오류: {type(e).__name__}: {e}")
            await asyncio.sleep(CHECK_INTERVAL)
            continue
        
        if found:
            logger.info(f"  🎯 {message}")
            
            # 월별로 한 번만 알림 발송
            if target_month not in alerted_months:
                send_email(
                    f"[네이버 예약] {target_month}월 빈 자리 발견!",
                    f"{message}\n\n"
                    f"자동 예약을 시도합니다...\n\n"
                    f"예약 페이지:\n{BOOKING_URL}",
                )
                alerted_months.add(target_month)
            
            # 자동 예약 실행
            try:
                logger.info(f"  🤖 자동 예약 시작...")
                success = await do_booking(target_month)
                if success:
                    booking_done = True
                else:
                    logger.warning(f"  예약 미확인 - {CHECK_INTERVAL}초 후 재시도")
            except Exception as e:
                logger.error(f"  예약 실패: {type(e).__name__}: {e}")
                logger.info(f"  {CHECK_INTERVAL}초 후 재시도")
                await asyncio.sleep(CHECK_INTERVAL)
                continue
        else:
            logger.info(f"  ℹ️  예약 불가 ({message})")
        
        if not booking_done:
            await asyncio.sleep(CHECK_INTERVAL)
    
    logger.info("\n" + "=" * 70)
    logger.info(" ✅ 예약 완료! 프로그램 종료.")
    logger.info("=" * 70)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n프로그램이 사용자에 의해 중단되었습니다.")
    except Exception as e:
        logger.error(f"\n프로그램 오류: {type(e).__name__}: {e}")
        raise
