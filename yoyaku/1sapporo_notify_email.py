# -*- coding: utf-8 -*-
"""
札幌市 小中学校体育館 空き枠監視（高速版・境界判定）
空き枠が出た瞬間の検知まで 1〜3 秒で動作します
"""

import time
import requests
import traceback
from typing import Set, List
from urllib.parse import urlencode

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ===== 設定 =====
DISCORD_WEBHOOK_URL = "https://discordapp.com/api/webhooks/1398139112413859982/K8iKLKKaZe-o3SbrbiJv6Et69EQOQdXfL9qAMRc-ddaEa3tquhPlpyfcM-HlsMCVUj6E"

TARGET_URL = "https://yoyaku.harp.lg.jp/sapporo/FacilitySearch/Index/?u%5B0%5D=70&ud=2026-02-16"
TARGET_MONTH = "2026-02-16"

INTERVAL_SEC =3    # 周期（最速：1.0秒）
HEADLESS = False       # 本番は True 推奨
RENDER_TIMEOUT = 5     # レンダリング待ち最短化（3秒）

# 予約不可リストの境界
BOUNDARY_TEXT_XPATH = "//span[contains(text(),'以下は希望日時に予約できません。')]"

# 空き施設の ID
AVAILABLE_FACILITY_SELECTOR = "span[id^='facility-']"


# ==============================
# Discord 通知
# ==============================
def send_discord(lines: List[str]) -> None:
    if not lines:
        return
    content = "【札幌・学校開放(小中体育館)】新たな空きが出ました！\n" + "\n".join(lines)
    r = requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
    if r.status_code != 204:
        print(f"[Warn] Discord通知失敗 status={r.status_code} body={r.text[:200]}")
    else:
        print("[OK] Discord通知完了")


# ==============================
# 空き状況リンク生成
# ==============================
def build_link(lgc: str, fc: str) -> str:
    base = f"https://yoyaku.harp.lg.jp/sapporo/FacilityAvailability/Index/{lgc}/{fc}"
    q = {"ptn": 1, "d": TARGET_MONTH}
    return f"{base}?{urlencode(q)}"


# ==============================
# Chrome Driver
# ==============================
def build_driver() -> webdriver.Chrome:
    options = Options()
    if HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1440,1200")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=options
    )


# ==============================
# レンダリング待ち
# ==============================
def wait_render(driver):
    """
    ・施設DOMが出るまで最大 3 秒待つ
    ・従来のように全ての facility- を待たないので高速
    """
    wait = WebDriverWait(driver, RENDER_TIMEOUT)
    wait.until(
        EC.presence_of_element_located((By.XPATH, BOUNDARY_TEXT_XPATH))
    )
    time.sleep(0.1)  # 安定化


# ==============================
# 境界より上の施設 = 空きあり
# ==============================
def collect_available_names(driver) -> Set[str]:
    boundary = driver.find_element(By.XPATH, BOUNDARY_TEXT_XPATH)
    boundary_y = boundary.location['y']

    elems = driver.find_elements(By.CSS_SELECTOR, AVAILABLE_FACILITY_SELECTOR)

    names = set()
    for e in elems:
        if e.location['y'] < boundary_y:
            t = (e.text or "").strip()
            if t:
                names.add(t)
    return names


def collect_available_with_links(driver) -> List[str]:
    boundary = driver.find_element(By.XPATH, BOUNDARY_TEXT_XPATH)
    boundary_y = boundary.location['y']

    elems = driver.find_elements(By.CSS_SELECTOR, AVAILABLE_FACILITY_SELECTOR)

    lines = []
    for e in elems:
        if e.location['y'] >= boundary_y:
            continue

        name = (e.text or "").strip()
        if not name:
            continue

        _id = e.get_attribute("id") or ""
        lgc, fc = None, None
        parts = _id.split("-")
        if len(parts) >= 3:
            lgc, fc = parts[1], parts[2]

        if lgc and fc:
            lines.append(f"・{name}\n  {build_link(lgc, fc)}")
        else:
            lines.append(f"・{name}")

    return lines


# ==============================
# メインループ
# ==============================
def main():
    print("[Start] 空き枠監視（高速境界版）を開始します")

    driver = build_driver()
    driver.get(TARGET_URL)

    prev: Set[str] = set()
    first = True

    try:
        while True:
            try:
                # ページ全体更新
                driver.refresh()
                wait_render(driver)

                # 空き施設の抽出（最速）
                names = collect_available_names(driver)
                added = sorted(list(names - prev))

                print(f"[Info] 空き: {len(names)}件 / 増分: {len(added)}件")

                if not first and added:
                    all_lines = collect_available_with_links(driver)
                    notify = []

                    for line in all_lines:
                        if not line.startswith("・"):
                            continue
                        school = line.split("\n", 1)[0].lstrip("・").strip()
                        if school in added:
                            notify.append(line)

                    send_discord(notify)

                first = False
                prev = names

            except Exception as e:
                print("[Error] 例外発生:", e)
                traceback.print_exc()
                try:
                    driver.save_screenshot("error.png")
                except:
                    pass
                requests.post(
                    DISCORD_WEBHOOK_URL,
                    json={"content": f"【エラー】監視中に例外が発生しました\n```\n{e}\n```"}
                )

            time.sleep(INTERVAL_SEC)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
