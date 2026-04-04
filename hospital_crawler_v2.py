"""
병원 데이터 크롤링 - 동적 로딩 대응 버전
JavaScript 렌더링이 완료될 때까지 기다림
"""
import asyncio
import sys
import traceback
from datetime import datetime
from playwright.async_api import async_playwright

# 로그 파일 설정
log_file = open("crawler_log.txt", "w", encoding="utf-8")

def log(message):
    """터미널과 파일 둘 다 출력"""
    print(message)
    log_file.write(message + "\n")
    log_file.flush()

async def debug_naver_place():
    """네이버 플레이스 구조 확인"""
    try:
        log("=" * 50)
        log("크롤러 시작 (동적 로딩 대응 버전)")
        log("=" * 50)
        
        async with async_playwright() as p:
            log("Playwright 초기화 중...")
            browser = await p.chromium.launch(headless=False)
            log("✅ 브라우저 실행 성공")
            
            page = await browser.new_page()
            log("✅ 새 페이지 생성 성공")
            
            # 네이버 플레이스 검색 (PC 버전 시도)
            search_query = "강남구 피부과"
            
            # 모바일 버전 대신 PC 버전 시도
            url = f"https://map.naver.com/p/search/{search_query}"
            
            log(f"\n검색 URL: {url}")
            log("페이지 로딩 중... (네트워크가 안정될 때까지 기다림)")
            
            # networkidle 옵션: 네트워크 요청이 거의 없을 때까지 기다림
            await page.goto(url, wait_until="networkidle")
            log("✅ 페이지 로딩 완료 (networkidle)")
            
            # 추가 대기
            await page.wait_for_timeout(5000)
            log("✅ 5초 추가 대기 완료")
            
            # 스크린샷 저장
            await page.screenshot(path="debug_screenshot_v2.png", full_page=True)
            log("✅ 스크린샷 저장: debug_screenshot_v2.png")
            
            # HTML 저장
            html = await page.content()
            with open("debug_page_v2.html", "w", encoding="utf-8") as f:
                f.write(html)
            log("✅ HTML 저장: debug_page_v2.html")
            
            # URL 확인
            current_url = page.url
            log(f"\n현재 URL: {current_url}")
            
            # 페이지 제목
            title = await page.title()
            log(f"페이지 제목: {title}")
            
            # PC 버전용 셀렉터 테스트
            log("\n=== 셀렉터 테스트 (PC 버전) ===")
            
            selectors_to_test = [
                # PC 버전 네이버 지도 셀렉터
                "li.UEzoS",  # 검색 결과 아이템
                "span.TYaxT",  # 업체명
                "a.tzwk0",  # 링크
                "div.zD5Nm",  # 평점
                "ul.rLcul",  # 검색 결과 리스트
                # 일반 셀렉터
                "li",
                "a",
                "span",
                "div[class*='search']",
                "div[class*='place']",
            ]
            
            for selector in selectors_to_test:
                try:
                    elements = await page.query_selector_all(selector)
                    log(f"{selector}: {len(elements)}개 발견")
                    
                    if 0 < len(elements) < 30:
                        # 처음 몇 개 요소의 텍스트 출력
                        for i, elem in enumerate(elements[:5]):
                            try:
                                text = await elem.inner_text()
                                cleaned = text.replace("\n", " ").strip()[:100]
                                if cleaned:
                                    log(f"  [{i}] {cleaned}")
                            except:
                                pass
                            
                except Exception as e:
                    log(f"{selector}: 에러 - {str(e)}")
            
            log("\n브라우저 창을 직접 확인하세요.")
            log("검색 결과가 보이나요?")
            log("\n엔터키를 누르면 종료됩니다...")
            
            await browser.close()
            log("✅ 브라우저 종료")
            
    except Exception as e:
        log("\n" + "=" * 50)
        log("🚨 에러 발생!")
        log("=" * 50)
        log(f"에러 타입: {type(e).__name__}")
        log(f"에러 메시지: {str(e)}")
        log("\n전체 스택 트레이스:")
        log(traceback.format_exc())

if __name__ == "__main__":
    try:
        asyncio.run(debug_naver_place())
    except Exception as e:
        log(f"\n최상위 에러: {str(e)}")
        log(traceback.format_exc())
    finally:
        log_file.close()
        print("\n\n모든 로그가 crawler_log.txt에 저장되었습니다.")
        input("엔터키를 눌러 종료...")
