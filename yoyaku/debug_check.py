# -*- coding: utf-8 -*-
"""
修正後のセレクタで空き検出テスト (2026-02-17)
"""

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

LOGIN_URL = "https://yoyaku.harp.lg.jp/sapporo/Login"
SAPPORO_ID = os.getenv("SAPPORO_ID") or "00157875"
SAPPORO_PW = os.getenv("SAPPORO_PW") or "kankyou5623"
TARGET_URL = "https://yoyaku.harp.lg.jp/sapporo/FacilitySearch/Index/?u%5B0%5D=70&ud=2026-02-17"

BOUNDARY_XPATH = "//span[contains(text(),'以下は希望日時に予約できません。')]"
FACILITY_CSS = "span[id^='facility2-']"


def build_driver():
    options = Options()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1500,1200")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=options
    )
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.navigator.chrome = {runtime: {}};
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['ja-JP', 'ja', 'en-US', 'en']});
            """
        },
    )
    return driver


def main():
    driver = build_driver()

    print("=== ログイン ===")
    wait = WebDriverWait(driver, 15)
    driver.get(LOGIN_URL)
    time.sleep(2)

    if "Incapsula" in driver.page_source:
        print("Incapsula待機中...")
        time.sleep(10)
        driver.get(LOGIN_URL)
        time.sleep(3)

    user_box = wait.until(EC.presence_of_element_located((By.NAME, "userId")))
    pass_box = wait.until(EC.presence_of_element_located((By.NAME, "password")))
    user_box.clear()
    user_box.send_keys(SAPPORO_ID)
    pass_box.clear()
    pass_box.send_keys(SAPPORO_PW)
    login_btn = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[.//span[contains(text(),'ログイン')]]")
        )
    )
    driver.execute_script("arguments[0].click();", login_btn)
    time.sleep(3)
    print(f"ログイン後URL: {driver.current_url}")

    print("\n=== 施設検索ページ ===")
    driver.get(TARGET_URL)

    # facility2- が表示されるまで待つ
    try:
        WebDriverWait(driver, 15).until(
            lambda d: (
                d.find_elements(By.CSS_SELECTOR, FACILITY_CSS)
                or d.find_elements(By.XPATH, BOUNDARY_XPATH)
            )
        )
        time.sleep(0.3)
    except Exception:
        print("タイムアウト: facility2- も境界テキストも見つかりません")

    # facility2- 全件
    elems = driver.find_elements(By.CSS_SELECTOR, FACILITY_CSS)
    print(f"\nfacility2- 要素数: {len(elems)}")
    for e in elems[:20]:
        fid = e.get_attribute("id")
        name = e.text.strip()
        y = e.location["y"]
        print(f"  id={fid}  name={name!r}  y={y}")

    # 境界テキスト
    boundaries = driver.find_elements(By.XPATH, BOUNDARY_XPATH)
    print(f"\n境界テキスト要素数: {len(boundaries)}")
    for b in boundaries:
        print(f"  y={b.location['y']}  text={b.text!r}")

    # 空きあり判定
    if boundaries:
        boundary_y = boundaries[0].location["y"]
        available = [(e.text.strip(), e.get_attribute("id")) for e in elems if e.location["y"] < boundary_y and e.text.strip()]
        print(f"\n=== 空きあり施設: {len(available)}件 ===")
        for name, fid in available:
            parts = fid.split("-")
            lgc, fc = parts[1], parts[2]
            print(f"  {name} (lgc={lgc}, fc={fc})")

        unavailable = [(e.text.strip(), e.get_attribute("id")) for e in elems if e.location["y"] >= boundary_y and e.text.strip()]
        print(f"\n=== 空きなし施設: {len(unavailable)}件 ===")
        for name, fid in unavailable[:5]:
            print(f"  {name}")
    else:
        print("\n境界テキストなし → 全件空きあり？")
        for e in elems[:10]:
            print(f"  {e.text.strip()}")

    # HTMLを保存
    with open("D:/yoyaku/debug_page.html", "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print("\nHTML保存: D:/yoyaku/debug_page.html")

    print("\n=== テスト完了 ===")
    driver.quit()


if __name__ == "__main__":
    main()
