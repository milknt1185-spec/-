# -*- coding: utf-8 -*-
"""
札幌市 体育館 自動予約スクリプト（完全版）
・自動ログイン
・空き監視
・空き状況ボタンを v-card 構造からクリック
・ポップアップ自動スキップ
・時間帯自動選択（土日祝: 17:45 → 19:15 / 平日: 19:15 → 17:45）
・空きなし → 監視復帰
・予約処理（確認 → 申込 → 人数16 → 支払方法へ）
・予約完了時 Discord 通知

使い方:
    python auto_reserve.py 2026-03-21
"""

import os
import sys
import time
import traceback
import datetime
from typing import Set, List

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# ==========================
# 設定
# ==========================

LOGIN_URL = "https://yoyaku.harp.lg.jp/sapporo/Login"

SAPPORO_ID = os.getenv("SAPPORO_ID") or "00157875"
SAPPORO_PW = os.getenv("SAPPORO_PW") or "kankyou5623"

DISCORD_WEBHOOK_URL = (
    "https://discordapp.com/api/webhooks/"
    "1398139112413859982/K8iKLKKaZe-o3SbrbiJv6Et69EQOQdXfL9qAMRc-ddaEa3tquhPlpyfcM-HlsMCVUj6E"
)

INTERVAL_SEC = 1          # 監視間隔（秒）
RENDER_TIMEOUT = 10       # 描画待ち上限（秒）
HEADLESS = False          # 本番は True でもOK


# ==========================
# 日付・時間帯設定
# ==========================

def get_target_month() -> str:
    """コマンドライン引数から日付を取得。なければエラー終了。"""
    if len(sys.argv) >= 2:
        date_str = sys.argv[1]
        try:
            datetime.date.fromisoformat(date_str)
            return date_str
        except ValueError:
            print(f"[Error] 日付の形式が不正です: {date_str}（例: 2026-03-21）")
            sys.exit(1)
    else:
        print("[Error] 日付を引数で指定してください。例: python auto_reserve.py 2026-03-21")
        sys.exit(1)


def is_holiday_jp(date: datetime.date) -> bool:
    """
    簡易的な日本の祝日判定。
    正確な判定が必要な場合は jpholiday ライブラリの導入を推奨。
    """
    try:
        import jpholiday
        return jpholiday.is_holiday(date)
    except ImportError:
        # jpholiday が入っていない場合は祝日判定なし
        return False


def get_time_slots(date_str: str) -> List[str]:
    """
    曜日に応じて優先時間帯リストを返す。
    土日祝: 17:45 → 19:15
    平日:   19:15 → 17:45
    """
    date = datetime.date.fromisoformat(date_str)
    weekday = date.weekday()  # 0=月, 5=土, 6=日
    is_weekend = weekday >= 5
    is_hol = is_holiday_jp(date)

    if is_weekend or is_hol:
        print(f"[Info] {date_str} は土日祝 → 17:45 優先")
        return [
            "17時45分から21時45分 利用可能",
            "19時15分から21時45分 利用可能",
        ]
    else:
        print(f"[Info] {date_str} は平日 → 19:15 優先")
        return [
            "19時15分から21時45分 利用可能",
            "17時45分から21時45分 利用可能",
        ]


# ==========================
# Discord
# ==========================

def send_discord(msg: str) -> None:
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=10)
        if r.status_code != 204:
            print(f"[Warn] Discord通知失敗: {r.status_code}")
        else:
            print("[OK] Discord通知:", msg)
    except Exception as e:
        print("[Error] Discord通知エラー:", e)


def send_discord_lines(lines: List[str]):
    if not lines:
        return
    msg = "【札幌・体育館】新たな空きが出ました！\n" + "\n".join(lines)
    send_discord(msg)


# ==========================
# Driver
# ==========================

def build_driver():
    options = Options()
    if HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1500,1200")

    return webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=options
    )


# ==========================
# ログイン
# ==========================

def login(driver):
    wait = WebDriverWait(driver, 15)
    driver.get(LOGIN_URL)

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

    # ログイン完了確認（URLが変わるか、ログインページでなくなるまで待つ）
    try:
        WebDriverWait(driver, 10).until(
            lambda d: LOGIN_URL not in d.current_url or "Error" in d.page_source
        )
    except Exception:
        pass

    time.sleep(1)

    # ログイン失敗チェック
    if "ログイン" in driver.title or "Login" in driver.current_url:
        if "パスワード" in driver.page_source or "認証" in driver.page_source:
            print("[Error] ログイン失敗。IDまたはパスワードを確認してください。")
            driver.quit()
            sys.exit(1)

    print("[OK] ログイン完了")


# ==========================
# 施設一覧ページ
# ==========================

BOUNDARY_TEXT_XPATH = "//span[contains(text(),'以下は希望日時に予約できません。')]"
AVAILABLE_FACILITY_SELECTOR = "span[id^='facility-']"


def wait_render(driver):
    """
    「以下は希望日時に予約できません。」の表示を待つ。
    表示されない場合は facility span が出るまで待つフォールバック。
    """
    try:
        WebDriverWait(driver, RENDER_TIMEOUT).until(
            EC.presence_of_element_located((By.XPATH, BOUNDARY_TEXT_XPATH))
        )
        time.sleep(0.2)
        return
    except Exception:
        pass

    # 境界テキストが出ないケース（全件空きあり等）へのフォールバック
    try:
        WebDriverWait(driver, RENDER_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, AVAILABLE_FACILITY_SELECTOR))
        )
        time.sleep(0.2)
    except Exception:
        print("[Warn] 施設リストの読み込み確認ができませんでした")


def collect_available_names(driver) -> Set[str]:
    """
    「以下は希望日時に予約できません。」より上にある facility-* を空きありとして取得。
    境界テキストがない場合は全 facility-* を空きありとして扱う。
    """
    elems = driver.find_elements(By.CSS_SELECTOR, AVAILABLE_FACILITY_SELECTOR)
    result: Set[str] = set()

    try:
        boundary = driver.find_element(By.XPATH, BOUNDARY_TEXT_XPATH)
        boundary_y = boundary.location["y"]

        for e in elems:
            if e.location["y"] < boundary_y:
                name = e.text.strip()
                if name:
                    result.add(name)
    except Exception:
        # 境界テキストがない場合 → 全件を空きありとして扱う
        for e in elems:
            name = e.text.strip()
            if name:
                result.add(name)

    return result


def collect_available_with_links(driver, target_month: str) -> List[str]:
    """
    空き施設の名前とURLを収集する。
    """
    elems = driver.find_elements(By.CSS_SELECTOR, AVAILABLE_FACILITY_SELECTOR)
    lines: List[str] = []

    try:
        boundary = driver.find_element(By.XPATH, BOUNDARY_TEXT_XPATH)
        boundary_y = boundary.location["y"]
        use_boundary = True
    except Exception:
        boundary_y = float("inf")
        use_boundary = False

    for e in elems:
        if use_boundary and e.location["y"] >= boundary_y:
            continue

        name = e.text.strip()
        if not name:
            continue

        # facility-011002-0473 のようなIDから lgc, fc を取得
        _id = e.get_attribute("id")
        parts = _id.split("-")
        if len(parts) < 3:
            continue
        _, lgc, fc = parts[0], parts[1], parts[2]
        url = (
            f"https://yoyaku.harp.lg.jp/sapporo/FacilityAvailability/Index/{lgc}/{fc}"
            f"?ptn=1&d={target_month}"
        )

        lines.append(f"・{name}\n  {url}")

    return lines


# ==========================
# ポップアップ「スキップ」
# ==========================

def skip_popup_if_exists(driver) -> bool:
    try:
        btn = WebDriverWait(driver, 2).until(
            EC.element_to_be_clickable((By.XPATH, "//span[contains(text(),'スキップ')]"))
        )
        driver.execute_script("arguments[0].click();", btn)
        print("[OK] スキップボタンをクリック")
        time.sleep(0.5)  # ポップアップ消去後の待機
        return True
    except Exception:
        return False


# ==========================
# 時間帯選択
# ==========================

def click_time_slot(driver, monitor_url: str, time_slots: List[str]) -> bool:
    """
    指定された時間帯リストの順番に「利用可能」ボタンをクリックする。
    いずれも取れなければ監視画面に戻る。
    """
    wait = WebDriverWait(driver, 3)

    for title in time_slots:
        try:
            btn = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, f"//button[contains(@title,'{title}')]")
                )
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            time.sleep(0.2)
            driver.execute_script("arguments[0].click();", btn)
            print(f"[OK] 時間帯選択: {title}")
            return True
        except Exception:
            continue

    print("[Info] 希望時間帯に空き無し → 監視復帰")
    driver.get(monitor_url)
    return False


# ==========================
# 予約処理
# ==========================

def reserve_from_current_detail(driver, monitor_url: str) -> bool:
    """
    予約詳細ページから支払方法ページまで進む。
    失敗時は監視ページに戻る。
    """
    try:
        # 確認ボタン
        confirm = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'確認')]"))
        )
        driver.execute_script("arguments[0].click();", confirm)
        print("[OK] 確認をクリック")
        time.sleep(1)

        # 予約申込へ
        reserve_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'予約申込へ')]"))
        )
        driver.execute_script("arguments[0].click();", reserve_btn)
        print("[OK] 予約申込へをクリック")
        time.sleep(1)

        # 利用人数入力
        people_box = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='text']"))
        )
        people_box.clear()
        people_box.send_keys("16")
        print("[OK] 利用人数 16 を入力")
        time.sleep(0.5)

        # 支払方法へ（1回クリックし、ページ遷移を確認）
        pay_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//span[contains(.,'支払方法へ')]"))
        )
        driver.execute_script("arguments[0].click();", pay_btn)
        print("[OK] 『支払方法へ』をクリック")
        time.sleep(1.5)

        # 支払方法ページへの遷移確認
        # 「支払方法へ」ボタンが再度表示された場合はもう一度クリック
        try:
            pay_btn2 = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, "//span[contains(.,'支払方法へ')]"))
            )
            driver.execute_script("arguments[0].click();", pay_btn2)
            print("[OK] 『支払方法へ』を再クリック")
            time.sleep(1.5)
        except Exception:
            pass  # ボタンが消えていれば遷移済み

        # 支払方法ページの確認
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'支払方法')]"))
        )

        print("[OK] 支払方法ページに遷移しました")
        send_discord("予約が完了しました！支払方法を選択してください。")
        return True

    except Exception as e:
        print("[Error] 予約処理エラー:", e)
        traceback.print_exc()
        driver.get(monitor_url)
        return False


# ==========================
# 空き状況 → 時間帯 → 予約
# ==========================

def click_aki_and_reserve(driver, school_name: str, monitor_url: str, time_slots: List[str]) -> bool:
    """
    施設名 → 同じ v-card 内の「空き状況」ボタンをクリック → 時間帯選択 → 予約。
    """
    try:
        # 1. 施設名を含む v-card を取得
        card = driver.find_element(
            By.XPATH,
            f"//span[contains(text(),'{school_name}')]/ancestor::div[contains(@class,'v-card')]"
        )

        # 2. v-card 内の「空き状況」ボタンを探す
        try:
            btn = card.find_element(
                By.XPATH,
                ".//button[contains(., '空き状況')]"
            )
        except Exception:
            # テキストが取れない場合は material-icons を含むボタンを拾う
            btn = card.find_element(
                By.XPATH,
                ".//button[.//i[contains(@class,'material-icons')]]"
            )

        driver.execute_script("arguments[0].scrollIntoView(true);", btn)
        time.sleep(0.3)
        driver.execute_script("arguments[0].click();", btn)
        print(f"[OK] 『空き状況』ボタンをクリック → {school_name}")
        time.sleep(0.5)

        # 3. ポップアップスキップ
        skip_popup_if_exists(driver)

        # 4. 時間帯自動選択
        if not click_time_slot(driver, monitor_url, time_slots):
            return False

        # 5. 予約処理
        return reserve_from_current_detail(driver, monitor_url)

    except Exception as e:
        print(f"[Error] 空き状況クリックでエラー ({school_name}):", e)
        traceback.print_exc()
        driver.get(monitor_url)
        return False


# ==========================
# メインループ
# ==========================

def main():
    target_month = get_target_month()
    time_slots = get_time_slots(target_month)

    target_url = (
        f"https://yoyaku.harp.lg.jp/sapporo/FacilitySearch/Index/"
        f"?u%5B0%5D=70&ud={target_month}"
    )

    print(f"[Info] 監視対象: {target_url}")

    driver = build_driver()
    login(driver)

    driver.get(target_url)
    prev: Set[str] = set()
    reserved = False
    loop_count = 0

    while True:
        if reserved:
            print("[END] 予約完了 → スクリプト終了")
            break

        try:
            driver.refresh()
            wait_render(driver)

            names = collect_available_names(driver)
            added = sorted(list(names - prev))

            loop_count += 1
            print(f"[Info] #{loop_count} 空き: {len(names)}件 / 新規: {len(added)}件")

            if added:
                lines = collect_available_with_links(driver, target_month)
                new_lines = [
                    line for line in lines
                    if line.split("\n", 1)[0].lstrip("・").strip() in added
                ]
                # 初回以外はDiscord通知
                if loop_count > 1:
                    send_discord_lines(new_lines)

                for school in added:
                    print("[Try] 予約を試みます →", school)
                    success = click_aki_and_reserve(driver, school, target_url, time_slots)
                    if success:
                        reserved = True
                        break

                if not reserved:
                    # 予約失敗後は監視ページに戻る
                    driver.get(target_url)

            prev = names

        except Exception as e:
            print("[Error] 監視ループで例外:", e)
            traceback.print_exc()
            try:
                driver.get(target_url)
            except Exception:
                pass

        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
