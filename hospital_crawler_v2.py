"""
병원 데이터 크롤링 - 동적 로딩 대응 버전
JavaScript 렌더링이 완료될 때까지 기다림
"""
import asyncio
import csv
import sys
import traceback
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


def create_logger(log_path="crawler_log.txt"):
    """파일+터미널 동시 출력 로거 반환"""
    log_file = open(log_path, "w", encoding="utf-8")

    def log(message):
        print(message)
        log_file.write(message + "\n")
        log_file.flush()

    def close():
        log_file.close()

    return log, close


async def extract_hospital_data(frame):
    """검색 결과 iframe에서 병원 데이터 추출"""
    hospitals = []

    # 결과 목록 로드 대기
    try:
        await frame.wait_for_selector("li.UEzoS", timeout=10000)
    except PlaywrightTimeoutError:
        # 셀렉터가 변경됐을 수 있으므로 대체 셀렉터 시도
        try:
            await frame.wait_for_selector("ul.rLcul li", timeout=5000)
        except PlaywrightTimeoutError:
            return hospitals

    items = await frame.query_selector_all("li.UEzoS")
    if not items:
        items = await frame.query_selector_all("ul.rLcul li")

    for item in items:
        try:
            name_el = await item.query_selector("span.TYaxT")
            name = (await name_el.inner_text()).strip() if name_el else ""

            category_el = await item.query_selector("span.KCMnt")
            category = (await category_el.inner_text()).strip() if category_el else ""

            address_el = await item.query_selector("span.LDgIH")
            address = (await address_el.inner_text()).strip() if address_el else ""

            rating_el = await item.query_selector("span.h69bs")
            rating = (await rating_el.inner_text()).strip() if rating_el else ""

            review_el = await item.query_selector("span.MVx6e")
            review_count = (await review_el.inner_text()).strip() if review_el else ""

            if name:
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
    """네이버 지도에서 병원 데이터 크롤링"""
    log, close_log = create_logger()

    all_hospitals = []

    try:
        log("=" * 50)
        log(f"크롤러 시작: {search_query}")
        log(f"시작 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log("=" * 50)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            log("브라우저 실행 완료")

            page = await browser.new_page()

            url = f"https://map.naver.com/p/search/{search_query}"
            log(f"\n검색 URL: {url}")

            await page.goto(url, wait_until="domcontentloaded")
            log("페이지 로딩 완료")

            # searchIframe 대기 (네이버 지도는 결과를 iframe에 렌더링)
            try:
                await page.wait_for_selector("#searchIframe", timeout=15000)
                log("searchIframe 발견")
            except PlaywrightTimeoutError:
                log("searchIframe을 찾을 수 없습니다. 스크린샷을 확인하세요.")
                await page.screenshot(path="debug_screenshot_v2.png", full_page=True)
                html = await page.content()
                with open("debug_page_v2.html", "w", encoding="utf-8") as f:
                    f.write(html)
                return []

            for page_num in range(1, max_pages + 1):
                log(f"\n--- 페이지 {page_num} 수집 중 ---")

                # iframe 프레임 객체 가져오기
                frame = page.frame(name="searchIframe")
                if frame is None:
                    frame_element = await page.query_selector("#searchIframe")
                    if frame_element is None:
                        log("iframe을 찾을 수 없습니다.")
                        break
                    frame = await frame_element.content_frame()

                if frame is None:
                    log("iframe 컨텍스트를 가져올 수 없습니다.")
                    break

                hospitals = await extract_hospital_data(frame)
                log(f"  {len(hospitals)}개 항목 수집")
                all_hospitals.extend(hospitals)

                # 다음 페이지 버튼 클릭
                if page_num < max_pages:
                    try:
                        next_btn = await frame.query_selector("a.eUTV2[aria-label='다음 페이지']")
                        if next_btn is None:
                            # 대체 셀렉터
                            next_btn = await frame.query_selector("button.eUTV2:last-child")
                        if next_btn is None:
                            log("다음 페이지 버튼 없음. 마지막 페이지입니다.")
                            break
                        await next_btn.click()
                        await frame.wait_for_load_state("networkidle")
                        await page.wait_for_timeout(1500)
                    except PlaywrightTimeoutError:
                        log("다음 페이지 로딩 타임아웃")
                        break
                    except Exception as e:
                        log(f"다음 페이지 이동 실패: {e}")
                        break

            await browser.close()
            log("\n브라우저 종료")

    except Exception as e:
        log(f"\n오류 발생: {type(e).__name__}: {e}")
        log(traceback.format_exc())
    finally:
        log(f"\n총 {len(all_hospitals)}개 병원 데이터 수집 완료")
        close_log()

    return all_hospitals


def save_to_csv(hospitals, filename="hospitals.csv"):
    """병원 데이터를 CSV로 저장"""
    if not hospitals:
        print("저장할 데이터가 없습니다.")
        return

    fieldnames = ["이름", "카테고리", "주소", "평점", "리뷰수"]
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(hospitals)

    print(f"CSV 저장 완료: {filename} ({len(hospitals)}개)")


if __name__ == "__main__":
    search_query = sys.argv[1] if len(sys.argv) > 1 else "강남구 피부과"
    hospitals = asyncio.run(crawl_hospitals(search_query=search_query, max_pages=5))
    save_to_csv(hospitals)
    print("\n모든 로그가 crawler_log.txt에 저장되었습니다.")
