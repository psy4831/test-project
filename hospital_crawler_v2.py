"""
병원 데이터 크롤링 - 네이버 지도 iframe 대응 버전
"""
import asyncio
import csv
import sys
import traceback
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


def create_logger(log_path="crawler_log.txt"):
    log_file = open(log_path, "w", encoding="utf-8")

    def log(message):
        print(message)
        log_file.write(message + "\n")
        log_file.flush()

    def close():
        log_file.close()

    return log, close


async def get_search_frame(page, log):
    """네이버 지도 검색 결과 iframe 반환"""
    # iframe이 나타날 때까지 대기
    try:
        await page.wait_for_selector("#searchIframe", timeout=15000)
    except PlaywrightTimeoutError:
        log("오류: #searchIframe을 찾을 수 없습니다.")
        await page.screenshot(path="debug_screenshot.png", full_page=True)
        log("debug_screenshot.png 저장 완료 - 화면 상태를 확인하세요.")
        return None

    # frame 이름으로 시도
    frame = page.frame(name="searchIframe")
    if frame:
        log("iframe 접근 성공 (name 방식)")
        return frame

    # frame element로 시도
    frame_el = await page.query_selector("#searchIframe")
    if frame_el:
        frame = await frame_el.content_frame()
        if frame:
            log("iframe 접근 성공 (element 방식)")
            return frame

    log("오류: iframe 컨텍스트를 가져올 수 없습니다.")
    return None


async def detect_selectors(frame, log):
    """iframe 내부에서 실제 사용 가능한 셀렉터 탐지"""
    # 병원 목록 아이템 후보 셀렉터
    item_selectors = [
        "li.UEzoS",
        "ul.rLcul > li",
        "li[data-laim-exp-id]",
        "li.VLTHu",
        "div.Ryr1F li",
    ]

    # 이름 후보 셀렉터
    name_selectors = [
        "span.TYaxT",
        "span.place_bluelink",
        "strong.name",
        "span.name",
        "div.place_name span",
        "a.name",
    ]

    found_item_sel = None
    found_name_sel = None

    for sel in item_selectors:
        items = await frame.query_selector_all(sel)
        if len(items) > 0:
            log(f"  목록 셀렉터 발견: {sel} ({len(items)}개)")
            found_item_sel = sel
            break

    if found_item_sel:
        items = await frame.query_selector_all(found_item_sel)
        first_item = items[0]
        for sel in name_selectors:
            el = await first_item.query_selector(sel)
            if el:
                text = await el.inner_text()
                log(f"  이름 셀렉터 발견: {sel} (예: {text.strip()[:30]})")
                found_name_sel = sel
                break

    return found_item_sel, found_name_sel


async def extract_hospitals(frame, item_sel, log):
    """iframe에서 병원 데이터 추출"""
    hospitals = []
    items = await frame.query_selector_all(item_sel)
    log(f"  총 {len(items)}개 항목 발견")

    for item in items:
        try:
            # 이름 (여러 셀렉터 시도)
            name = ""
            for sel in ["span.TYaxT", "span.place_bluelink", "strong.name", "span.name"]:
                el = await item.query_selector(sel)
                if el:
                    name = (await el.inner_text()).strip()
                    break

            if not name:
                continue

            # 카테고리
            category = ""
            for sel in ["span.KCMnt", "span.category", "span.lnJFt"]:
                el = await item.query_selector(sel)
                if el:
                    category = (await el.inner_text()).strip()
                    break

            # 주소
            address = ""
            for sel in ["span.LDgIH", "span.jibun", "span.road"]:
                el = await item.query_selector(sel)
                if el:
                    address = (await el.inner_text()).strip()
                    break

            # 평점
            rating = ""
            for sel in ["span.h69bs", "span.rating", "span.orXYY"]:
                el = await item.query_selector(sel)
                if el:
                    rating = (await el.inner_text()).strip()
                    break

            # 리뷰수
            review_count = ""
            for sel in ["span.MVx6e", "span.review_count", "span.CKeJB"]:
                el = await item.query_selector(sel)
                if el:
                    review_count = (await el.inner_text()).strip()
                    break

            hospitals.append({
                "이름": name,
                "카테고리": category,
                "주소": address,
                "평점": rating,
                "리뷰수": review_count,
            })

        except Exception:
            continue

    return hospitals


async def crawl_hospitals(search_query="강남구 피부과", max_pages=5, headless=True):
    log, close_log = create_logger()
    all_hospitals = []

    try:
        log("=" * 50)
        log(f"크롤러 시작: {search_query}")
        log(f"시작 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log("=" * 50)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            url = f"https://map.naver.com/p/search/{search_query}"
            log(f"접속 URL: {url}")

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            log("페이지 로딩 완료")

            # iframe 가져오기
            frame = await get_search_frame(page, log)
            if frame is None:
                return []

            # 셀렉터 자동 탐지
            log("\n셀렉터 탐지 중...")
            await page.wait_for_timeout(3000)  # 콘텐츠 렌더링 대기
            item_sel, name_sel = await detect_selectors(frame, log)

            if not item_sel:
                log("오류: 병원 목록 셀렉터를 찾을 수 없습니다.")
                # iframe HTML 저장 (디버깅용)
                html = await frame.content()
                with open("debug_iframe.html", "w", encoding="utf-8") as f:
                    f.write(html)
                log("debug_iframe.html 저장 완료 - 셀렉터 확인 필요")
                return []

            # 페이지별 수집
            for page_num in range(1, max_pages + 1):
                log(f"\n--- 페이지 {page_num} 수집 중 ---")

                hospitals = await extract_hospitals(frame, item_sel, log)
                log(f"  {len(hospitals)}개 수집 완료")
                all_hospitals.extend(hospitals)

                # 다음 페이지
                if page_num < max_pages:
                    next_btn = None
                    for sel in [
                        "a.eUTV2[aria-label='다음 페이지']",
                        "button[aria-label='다음 페이지']",
                        "a.next",
                        "div.zRM9F > a:last-child",
                    ]:
                        next_btn = await frame.query_selector(sel)
                        if next_btn:
                            break

                    if next_btn is None:
                        log("다음 페이지 없음. 수집 종료.")
                        break

                    await next_btn.click()
                    await page.wait_for_timeout(2000)

            await browser.close()
            log("\n브라우저 종료")

    except Exception as e:
        log(f"\n오류 발생: {type(e).__name__}: {e}")
        log(traceback.format_exc())
    finally:
        log(f"\n총 {len(all_hospitals)}개 병원 수집 완료")
        close_log()

    return all_hospitals


def save_to_csv(hospitals, filename="hospitals.csv"):
    if not hospitals:
        print("저장할 데이터가 없습니다. crawler_log.txt를 확인하세요.")
        return

    fieldnames = ["이름", "카테고리", "주소", "평점", "리뷰수"]
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(hospitals)

    print(f"\nCSV 저장 완료: {filename} ({len(hospitals)}개)")


if __name__ == "__main__":
    search_query = sys.argv[1] if len(sys.argv) > 1 else "강남구 피부과"
    hospitals = asyncio.run(crawl_hospitals(search_query=search_query, max_pages=5))
    save_to_csv(hospitals)
    print("로그: crawler_log.txt")
