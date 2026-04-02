"""
네이버 로그인 세션 저장 스크립트

이 스크립트를 먼저 실행하면 naver_login.json 파일이 생성됩니다.
이 파일은 naver_booking_45_monthly.py에서 사용됩니다.

사용법:
    python save_login.py
"""

import asyncio
from playwright.async_api import async_playwright
import os


async def save_naver_login():
    """
    네이버 로그인 페이지를 열고,
    사용자가 수동으로 로그인한 후,
    세션 정보를 naver_login.json 파일로 저장합니다.
    """

    output_file = "naver_login.json"

    print("=" * 70)
    print(" 📝 네이버 로그인 세션 저장")
    print("=" * 70)
    print()
    print(" 📖 사용 방법:")
    print("    1. 아래 브라우저 창이 열립니다")
    print("    2. 네이버 계정(ID/PW)으로 로그인하세요")
    print("    3. 로그인 완료 후 브라우저를 닫으면 세션이 저장됩니다")
    print()
    print(" ⏱️  대기 시간: 60초 (로그인 완료 후 또는 타임아웃 시 자동 진행)")
    print()

    async with async_playwright() as p:
        # Chromium 브라우저 실행 (headless=False: 브라우저 창 보임)
        browser = await p.chromium.launch(headless=False, slow_mo=50)

        # 새 컨텍스트 생성 (세션 저장용)
        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            ),
        )
        page = await context.new_page()

        try:
            # 네이버 로그인 페이지 열기
            print(" 🔗 네이버 로그인 페이지 로딩 중...")
            await page.goto("https://nid.naver.com/nidlogin.login", wait_until="networkidle")
            print(" ✅ 페이지 로드 완료!")
            print()
            print(" 👉 위 브라우저 창에서 아이디/비밀번호를 입력하고 로그인하세요...")
            print()

            # 로그인 완료 대기 (최대 60초)
            # 로그인 성공하면 URL이 변경됨
            try:
                await page.wait_for_url(
                    lambda url: "nid.naver.com" not in url,
                    timeout=60000
                )
                print(" ✅ 로그인 완료!")
            except:
                print(" ⚠️  타임아웃 또는 로그인 미완료 → 진행합니다...")

            # 현재 URL 출력 (디버깅용)
            print(f" 현재 페이지: {page.url}")
            print()

            # 세션 정보 저장
            print(f" 💾 세션 저장 중 ({output_file})...")
            await context.storage_state(path=output_file)

            # 파일 존재 확인
            if os.path.exists(output_file):
                file_size = os.path.getsize(output_file)
                print(f" ✅ 세션 저장 완료!")
                print(f" 📂 파일: {output_file}")
                print(f" 📏 크기: {file_size} bytes")
                print()
                print("=" * 70)
                print(" ✨ 이제 naver_booking_45_monthly.py를 실행할 수 있습니다!")
                print("=" * 70)
            else:
                print(f" ❌ 세션 저장 실패: {output_file} 파일 생성 안 됨")

        except Exception as e:
            print(f" ❌ 오류 발생: {e}")

        finally:
            # 3초 대기 후 브라우저 종료
            print()
            print(" 🔄 3초 후 브라우저를 닫습니다...")
            await asyncio.sleep(3)
            await browser.close()
            print(" ✅ 완료!")


if __name__ == "__main__":
    try:
        asyncio.run(save_naver_login())
    except KeyboardInterrupt:
        print("\n\n ⚠️  사용자가 중단했습니다.")
    except Exception as e:
        print(f"\n\n ❌ 예상치 못한 오류: {e}")
