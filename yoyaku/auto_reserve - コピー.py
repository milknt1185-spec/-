# -*- coding: utf-8 -*-
"""
札幌市体育館 自動予約監視スクリプト（最新版）
・ログイン自動入力（input-21 / input-25対応）
・チュートリアル「スキップ」「読んだ」に対応
・18時以降の空き枠を検出して即クリック
・他ユーザー競合検出で自動リトライ
・Discord通知（予約成功のみ）
"""

import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ======== 設定 ========
LOGIN_URL = "https://yoyaku.harp.lg.jp/sapporo/Login"
SAPPORO_ID = os.getenv("SAPPORO_ID") or "00157875"
SAPPORO_PW = os.getenv("SAPPORO_PW") or "kankyou5623"
SPORT_SEARCH_URL = os.getenv("SPORT_SEARCH_URL") or "https://yoyaku.harp.lg.jp/sapporo/FacilitySearch/Index/?u%5B0%5D=70&ud=2025-10-22"
RETRY_URL = SPORT_SEARCH_URL
WAIT_SEC = 10

# ======== Discord設定 ========
DEFAULT_WEBHOOK_URL = "https://discordapp.com/api/webhooks/1398139112413859982/K8iKLKKaZe-o3SbrbiJv6Et69EQOQdXfL9qAMRc-ddaEa3tquhPlpyfcM-HlsMCVUj6E"
DISCORD_WEBHOOK_URL = (os.environ.get("DISCORD_WEBHOOK_URL") or DEFAULT_WEBHOOK_URL).strip()


def send_discord(msg: str):
    """Discordに通知を送信"""
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=10)
        if r.status_code == 204:
            print(f"[Discord] {msg}")
        else:
            print(f"[Warn] Discord通知失敗: {r.status_code}")
    except Exception as e:
        print(f"[Warn] Discord通知エラー: {e}")


# ======== Chrome起動 ========
chrome_options = Options()
chrome_options.add_argument("--start-maximized")
chrome_options.add_argument("--disable-notifications")
driver = webdriver.Chrome(options=chrome_options)
wait = WebDriverWait(driver, 15)

print(f"[Start] {time.strftime('%Y-%m-%d %H:%M:%S')} 自動監視開始")


# ======== ログイン ========
driver.get(LOGIN_URL)
print("[Info] ログインページアクセス中...")

try:
    # 安定検出：name属性ベースで取得
    user_box = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@name='userId' or @type='text']")))
    pass_box = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@name='password' or @type='password']")))

    user_box.clear()
    user_box.send_keys(SAPPORO_ID)
    pass_box.clear()
    pass_box.send_keys(SAPPORO_PW)
    print("[OK] ログイン情報を入力しました")

    # ログインボタンをクリック
    login_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//span[contains(.,'ログイン') and not(contains(.,'する'))]")))
    driver.execute_script("arguments[0].click();", login_btn)
    print("[OK] ログインボタンをクリックしました")

    # ログイン後のページ遷移を確認
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.XPATH, "//span[contains(.,'雨燈々') or contains(.,'ログアウト')]"))
    )
    print("[OK] ログイン完了")

except Exception as e:
    print(f"[Error] ログイン処理でエラー発生: {e}")
    driver.save_screenshot("login_error.png")
    print("[Error] ログインに失敗しました。login_error.pngを確認してください。")
    driver.quit()
    exit()


# ======== チュートリアルスキップ（スキップ／読んだ対応） ========
def skip_tutorial():
    """チュートリアルやポップアップをスキップ"""
    try:
        for keyword in ["スキップ", "次へ", "閉じる", "読んだ"]:
            buttons = driver.find_elements(By.XPATH, f"//span[contains(.,'{keyword}')]")
            for b in buttons:
                try:
                    driver.execute_script("arguments[0].click();", b)
                    print(f"[OK] '{keyword}' ボタンをクリックしました")
                    time.sleep(0.5)
                except:
                    pass
    except:
        pass


# ======== 他ユーザー予約競合検出 ========
def detect_conflict():
    """他の利用者が既に予約済みのときTrueを返す"""
    try:
        WebDriverWait(driver, 2).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'他の利用者が申込済')]"))
        )
        close_btn = driver.find_element(By.XPATH, "//button[contains(@aria-label,'閉じる') or .//i[contains(text(),'close')]]")
        driver.execute_script("arguments[0].click();", close_btn)
        print("[Warn] 他の利用者が既に予約済みでした。")
        return True
    except:
        return False


# ======== 予約処理 ========
def reserve_from_current_detail():
    try:
        confirm = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'確認')]")))
        driver.execute_script("arguments[0].click();", confirm)
        print("[OK] 確認をクリック")

        reserve_btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'予約申込へ')]")))
        driver.execute_script("arguments[0].click();", reserve_btn)
        print("[OK] 予約申込へをクリック")

        people_box = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//input[@type='text']")))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", people_box)
        people_box.clear()
        people_box.send_keys("16")
        print("[OK] 利用人数 16 を入力")

        for i in range(2):
            pay_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//span[contains(.,'支払方法へ')]")))
            driver.execute_script("arguments[0].click();", pay_btn)
            print(f"[OK] 『支払方法へ』をクリック ({i+1}/2)")
            time.sleep(1)

        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'支払方法')]")))
        send_discord("🎉 予約が完了しました！")
        print("[OK] 支払方法ページに遷移しました")
        return True

    except Exception as e:
        print(f"[Error] 予約処理中エラー: {e}")
        return False


# ======== メイン監視ループ ========
driver.get(SPORT_SEARCH_URL)
time.sleep(3)
skip_tutorial()

while True:
    try:
        skip_tutorial()
        print("[Info] 18時以降の空き枠（○）を探しています...")

        circles = driver.find_elements(
            By.XPATH,
            "//button[@title and contains(@title,'利用可能')]"
            "[contains(@title,'18時') or contains(@title,'19時') or contains(@title,'20時') or contains(@title,'21時')]"
            "//i[contains(text(),'trip_origin') and contains(@style,'rgb(23, 174, 154)')]"
        )

        if circles:
            print(f"[OK] 18時以降の利用可能枠を {len(circles)} 件発見。クリックします。")
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", circles[0])
            driver.execute_script("arguments[0].click();", circles[0])
            time.sleep(1)

            if detect_conflict():
                print("[Warn] 競合検出 → 再監視に戻ります。")
                driver.get(RETRY_URL)
                time.sleep(5)
                continue

            if reserve_from_current_detail():
                print("[Success] 予約完了！")
                break
            else:
                print("[Warn] 予約失敗。再監視を継続。")
                driver.get(RETRY_URL)
                time.sleep(5)
                continue

        else:
            print("[Info] 空き枠なし。10秒後に再読み込み。")
            time.sleep(WAIT_SEC)
            driver.refresh()
            skip_tutorial()
            continue

    except Exception as e:
        print(f"[Error] 監視中例外: {e}")
        driver.get(RETRY_URL)
        time.sleep(5)
        skip_tutorial()
        continue
