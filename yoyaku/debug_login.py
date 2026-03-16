# -*- coding: utf-8 -*-
"""
修正後の空き検出ロジック確認テスト (2026-02-18)
"""
import os, sys, time, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

LOGIN_URL  = "https://yoyaku.harp.lg.jp/sapporo/Login"
TARGET_URL = "https://yoyaku.harp.lg.jp/sapporo/FacilitySearch/Index/?u%5B0%5D=70&ud=2026-02-18"
SAPPORO_ID = "00157875"
SAPPORO_PW = "kankyou5623"
BOUNDARY_XPATH = "//span[contains(text(),'以下は希望日時に予約できません。')]"

def build_driver():
    opt = Options()
    opt.add_argument("--disable-gpu")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--window-size=1500,1200")
    opt.add_argument("--disable-blink-features=AutomationControlled")
    opt.add_experimental_option("excludeSwitches", ["enable-automation"])
    opt.add_experimental_option("useAutomationExtension", False)
    opt.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    drv = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=opt)
    drv.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        window.navigator.chrome = {runtime: {}};
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['ja-JP','ja','en-US','en']});
    """})
    return drv

def main():
    drv = build_driver()
    wait = WebDriverWait(drv, 15)

    print("=== ログイン ===")
    drv.get(LOGIN_URL)
    time.sleep(3)
    if "Incapsula" in drv.page_source:
        print("Incapsula待機15秒...")
        time.sleep(15)
        if "Incapsula" in drv.page_source:
            drv.get(LOGIN_URL); time.sleep(5)

    wait.until(EC.presence_of_element_located((By.NAME, "userId"))).send_keys(SAPPORO_ID)
    wait.until(EC.presence_of_element_located((By.NAME, "password"))).send_keys(SAPPORO_PW)
    btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[.//span[contains(text(),'ログイン')]]")))
    drv.execute_script("arguments[0].click();", btn)
    try:
        WebDriverWait(drv, 10).until(lambda d: "/Login" not in d.current_url)
    except: pass
    print(f"ログイン後URL: {drv.current_url}")

    print(f"\n=== 施設検索ページ ===")
    drv.get(TARGET_URL)

    # 描画待ち
    try:
        WebDriverWait(drv, 20).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, "span[id^='facility']")
                   or d.find_elements(By.XPATH, BOUNDARY_XPATH)
        )
        time.sleep(1)
    except:
        print("描画タイムアウト")

    # 境界テキストY座標
    bds = drv.find_elements(By.XPATH, BOUNDARY_XPATH)
    boundary_y = bds[0].location["y"] if bds else float("inf")
    print(f"境界テキスト y={boundary_y}")

    # 全 facility- 系要素を取得
    all_elems = drv.find_elements(By.CSS_SELECTOR, "span[id^='facility']")
    print(f"\n全 facility 系要素: {len(all_elems)}件")

    available = []
    for e in all_elems:
        fid  = e.get_attribute("id") or ""
        name = e.text.strip()
        y    = e.location["y"]
        is_available = not fid.startswith("facility2-") and y < boundary_y
        mark = "✓空きあり" if is_available else "  空きなし"
        print(f"  {mark}  id={fid}  name={name!r}  y={y}")
        if is_available and name:
            parts = fid.split("-")
            if len(parts) >= 3:
                available.append((name, parts[1], parts[2]))

    print(f"\n=== 空きあり施設: {len(available)}件 ===")
    for name, lgc, fc in available:
        avail_url = f"https://yoyaku.harp.lg.jp/sapporo/FacilityAvailability/Index/{lgc}/{fc}?ptn=1&d=2026-02-18"
        print(f"  {name}  lgc={lgc}  fc={fc}")
        print(f"    → {avail_url}")

    drv.quit()
    print("\n=== テスト完了 ===")

if __name__ == "__main__":
    main()
