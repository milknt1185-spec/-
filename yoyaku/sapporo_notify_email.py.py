# -*- coding: utf-8 -*-
"""
札幌市 施設一覧・検索（学校開放/バレー upi=70, 2025-12）監視
- 初回だけ対象URLを開く（以降は開きっぱなし）
- 20秒ごとに「再度読み込み」ボタンをクリック（無ければ driver.refresh()）
- 「空きあり」側の施設名: span[id^='facility-'] を抽出
- 前回より増えたときだけ Discord Webhook に通知（初回は通知しない）
必要:
    pip install selenium webdriver-manager requests
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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ===== 設定 =====
DISCORD_WEBHOOK_URL = "https://discordapp.com/api/webhooks/1398139112413859982/K8iKLKKaZe-o3SbrbiJv6Et69EQOQdXfL9qAMRc-ddaEa3tquhPlpyfcM-HlsMCVUj6E"
TARGET_URL = TARGET_URL = "https://yoyaku.harp.lg.jp/sapporo/FacilitySearch/Index/?u%5B0%5D=70&ud=2026-01-23"
TARGET_MONTH = "2026-01-23"

INTERVAL_SEC = 0.5      # 20秒ごとに更新
HEADLESS = False       # 目視するなら False、本運用は True 推奨
RENDER_TIMEOUT = 30    # DOM描画待ちの最大秒数

# 「空きあり」側（オレンジ枠外）の施設名（facility- で始まるID）
AVAILABLE_FACILITY_SELECTOR = "span[id^='facility-']"

def send_discord(lines: List[str]) -> None:
    if not lines:
        return
    content = "【札幌・学校開放(バレー) 8月】新たな空きが見つかりました！\n" + "\n".join(lines)
    r = requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=15)
    if r.status_code != 204:
        print(f"[Warn] Discord通知失敗 status={r.status_code} body={r.text[:200]}")
    else:
        print("[OK] Discord通知完了")

def build_link(lgc: str, fc: str) -> str:
    base = f"https://yoyaku.harp.lg.jp/sapporo/FacilityAvailability/Index/{lgc}/{fc}"
    q = {"ptn": 1, "d": TARGET_MONTH}
    return f"{base}?{urlencode(q)}"

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
    return webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()),
                            options=options)

def wait_render(driver: webdriver.Chrome) -> None:
    """空きあり/空きなしのどちらかが出るまで待つ（スクロールはしない）"""
    wait = WebDriverWait(driver, RENDER_TIMEOUT)
    wait.until(
        EC.any_of(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, AVAILABLE_FACILITY_SELECTOR)),
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'以下は希望日時に予約できません。')]")),
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'該当する施設・室場がありません。')]")),
        )
    )
    time.sleep(0.8)  # 安定待ち（短め）

def reload_page(driver: webdriver.Chrome) -> None:
    """
    20秒ごとに呼ばれる再読み込みアクション。
    1) 画面内の『再度読み込み』を含むボタンがあればクリック（スクロールなし）
    2) 見つからなければ driver.refresh()
    """
    try:
        candidates = driver.find_elements(
            By.XPATH,
            "//button[contains(., '再度読み込み')]"
            "|//button[.//span[contains(., '再度読み込み')]]"
            "|//button[.//div[contains(., '再度読み込み')]]"
        )
        if candidates:
            try:
                candidates[0].click()
                return
            except Exception:
                pass
        driver.refresh()
    except Exception:
        driver.refresh()

def collect_available_names(driver: webdriver.Chrome) -> Set[str]:
    """空きあり側の施設名を集合で返す（スクロールなし）"""
    elems = driver.find_elements(By.CSS_SELECTOR, AVAILABLE_FACILITY_SELECTOR)
    return {e.text.strip() for e in elems if (e.text or "").strip()}

def collect_available_with_links(driver: webdriver.Chrome) -> List[str]:
    """
    施設名に空き状況リンクを付けて行テキスト化。
    facility- のIDは 'facility-{lgc}-{fc}' 形式なので、そこから lgc, fc を抜く。
    """
    lines: List[str] = []
    elems = driver.find_elements(By.CSS_SELECTOR, AVAILABLE_FACILITY_SELECTOR)
    for e in elems:
        name = (e.text or "").strip()
        _id = e.get_attribute("id") or ""
        # 例: facility-011002-0431
        lgc, fc = None, None
        try:
            parts = _id.split("-")
            if len(parts) >= 3:
                lgc, fc = parts[1], parts[2]
        except Exception:
            pass
        if name:
            if lgc and fc:
                lines.append(f"・{name}\n  {build_link(lgc, fc)}")
            else:
                lines.append(f"・{name}")
    return lines

def main():
    print("[Start] 8月の空き監視（バレー）を開始。増えた時だけ通知します。（スクロールなし）")
    driver = build_driver()
    driver.get(TARGET_URL)

    prev: Set[str] = set()
    first = True

    try:
        while True:
            try:
                reload_page(driver)   # ボタン→なければrefresh
                wait_render(driver)   # 描画待ち
                names = collect_available_names(driver)
                added = sorted(list(names - prev))
                print(f"[Info] 空きあり: {len(names)}件 / 増分: {len(added)}件")

                # 初回は通知しない（基準化）
                if not first and added:
                    # 追加分だけリンク付きで通知
                    lines_all = collect_available_with_links(driver)
                    # lines_all から今回追加の施設だけ抽出
                    lines = []
                    for line in lines_all:
                        # 行頭の "・学校名" を拾って照合
                        if not line.startswith("・"):
                            continue
                        name_line = line.split("\n", 1)[0].lstrip("・").strip()
                        if name_line in added:
                            lines.append(line)
                    send_discord(lines)

                prev = names
                first = False

            except Exception as e:
                print(f"[Error] 例外: {e}")
                traceback.print_exc()
                try:
                    driver.save_screenshot("last_page.png")
                    print("[Debug] last_page.png を保存しました。")
                except Exception:
                    pass

            print(f"[Wait] 次回チェックまで {INTERVAL_SEC} 秒")
            time.sleep(INTERVAL_SEC)

    finally:
        driver.quit()

if __name__ == "__main__":
    main()