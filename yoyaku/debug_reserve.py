# -*- coding: utf-8 -*-
"""
予約フロー詳細デバッグ - 日付クリック後の時間帯ボタン構造確認
"""
import os, sys, time, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

LOGIN_URL  = "https://yoyaku.harp.lg.jp/sapporo/Login"
AVAIL_URL  = "https://yoyaku.harp.lg.jp/sapporo/FacilityAvailability/Index/011002/0258?ptn=1&d=2026-02-18"

SAPPORO_ID = "00157875"
SAPPORO_PW = "kankyou5623"
DISCORD_WEBHOOK = (
    "https://discordapp.com/api/webhooks/"
    "1398139112413859982/K8iKLKKaZe-o3SbrbiJv6Et69EQOQdXfL9qAMRc-ddaEa3tquhPlpyfcM-HlsMCVUj6E"
)

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

def send_discord(msg):
    try:
        r = requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
        print(f"Discord: status={r.status_code}")
    except Exception as e:
        print(f"Discord送信エラー: {e}")

def dump_buttons(drv, label=""):
    btns = drv.find_elements(By.TAG_NAME, "button")
    print(f"\n--- ボタン一覧 [{label}] 全{len(btns)}件 ---")
    for b in btns:
        title = b.get_attribute("title") or ""
        text  = b.text.strip().replace("\n", " ")
        combined = title or text
        if combined:
            print(f"  title={title[:60]!r}  text={text[:40]!r}")

def main():
    drv = build_driver()
    wait = WebDriverWait(drv, 15)

    # ---- Discord テスト ----
    print("=== Discord通知テスト ===")
    send_discord("【テスト開始】予約フロー確認スクリプトを起動しました。")

    # ---- ログイン ----
    print("\n=== ログイン ===")
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
    time.sleep(1)
    print(f"ログイン: {drv.current_url}")

    # ---- 空き状況ページ ----
    print("\n=== 空き状況ページ ===")
    drv.get(AVAIL_URL)
    time.sleep(3)
    print(f"URL: {drv.current_url}")

    # スキップ
    try:
        skip = WebDriverWait(drv, 3).until(
            EC.element_to_be_clickable((By.XPATH, "//span[contains(text(),'スキップ')]"))
        )
        drv.execute_script("arguments[0].click();", skip)
        print("スキップクリック")
        time.sleep(1)
    except: pass

    # 警告メッセージ確認
    warnings = drv.find_elements(By.XPATH, "//*[contains(text(),'個人登録')]")
    if warnings:
        print(f"\n⚠️ 警告あり: {warnings[0].text[:100]}")
    else:
        print("\n警告なし（この施設は予約可能）")

    # ---- STEP1: 「今日 2月18日水曜日 利用可能」日付ボタンをクリック ----
    print("\n=== STEP1: 日付クリック (2月18日) ===")
    dump_buttons(drv, "日付クリック前")

    try:
        # 「利用可能」を含む今日の日付ボタン
        date_btn = WebDriverWait(drv, 5).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(@title,'2月18日') and contains(@title,'利用可能')]")
            )
        )
        print(f"日付ボタン: {date_btn.get_attribute('title')}")
        drv.execute_script("arguments[0].click();", date_btn)
        print("日付クリック完了")
        time.sleep(2)
    except Exception as e:
        print(f"日付ボタンなし: {e}")

    # クリック後のボタン変化を確認
    dump_buttons(drv, "日付クリック後")

    # ---- STEP2: 時間帯ボタン探索 ----
    print("\n=== STEP2: 時間帯ボタン探索 ===")

    # パターンA: title に「時分」を含む
    time_btns = drv.find_elements(By.XPATH, "//button[contains(@title,'分') and contains(@title,'可能')]")
    print(f"時間帯ボタン(分+可能): {len(time_btns)}件")
    for b in time_btns[:10]:
        print(f"  title={b.get_attribute('title')[:80]!r}")

    # パターンB: 「夜間」「午後」チェックボックス
    night_elems = drv.find_elements(By.XPATH, "//*[contains(text(),'夜間')]")
    print(f"\n夜間テキスト要素: {len(night_elems)}件")
    for e in night_elems[:5]:
        print(f"  tag={e.tag_name}  text={e.text[:40]!r}")

    # パターンC: radioボタン
    radios = drv.find_elements(By.XPATH, "//input[@type='radio']")
    print(f"\nradioボタン: {len(radios)}件")
    for r in radios[:10]:
        print(f"  value={r.get_attribute('value')!r}  name={r.get_attribute('name')!r}")

    # パターンD: checkboxボタン
    checks = drv.find_elements(By.XPATH, "//input[@type='checkbox']")
    print(f"\ncheckboxボタン: {len(checks)}件")
    for c in checks[:10]:
        print(f"  value={c.get_attribute('value')!r}  name={c.get_attribute('name')!r}")

    # パターンE: 「利用可能」を含む全ボタン
    avail_btns = drv.find_elements(By.XPATH, "//button[contains(@title,'利用可能')]")
    print(f"\n利用可能ボタン全件: {len(avail_btns)}件")
    for b in avail_btns[:10]:
        print(f"  title={b.get_attribute('title')[:80]!r}")

    # HTMLを保存
    with open("D:/yoyaku/debug_after_date_click.html", "w", encoding="utf-8") as f:
        f.write(drv.page_source)
    print("\nHTML保存: debug_after_date_click.html")

    # ---- STEP3: 「利用可能」ボタンが時間帯ならクリック ----
    clicked_slot = False
    for title_keyword in ["17時45分", "19時15分", "夜間", "18時", "17時"]:
        btns = drv.find_elements(By.XPATH, f"//button[contains(@title,'{title_keyword}')]")
        if btns:
            print(f"\n時間帯ボタン発見 [{title_keyword}]: {btns[0].get_attribute('title')}")
            drv.execute_script("arguments[0].scrollIntoView(true);", btns[0])
            time.sleep(0.3)
            drv.execute_script("arguments[0].click();", btns[0])
            print("時間帯クリック完了")
            time.sleep(2)
            clicked_slot = True
            break

    if not clicked_slot:
        print("\n時間帯ボタンが見つかりません。ページ構造を確認してください。")
        print(f"現在URL: {drv.current_url}")
        drv.quit()
        return

    # ---- STEP4以降: 確認→申込→人数→支払方法 ----
    print("\n=== STEP4: 確認ボタン ===")
    dump_buttons(drv, "時間帯クリック後")

    try:
        confirm = WebDriverWait(drv, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'確認')]"))
        )
        print(f"確認ボタン: {confirm.text!r}")
        drv.execute_script("arguments[0].click();", confirm)
        time.sleep(2)
        print(f"URL: {drv.current_url}")
    except Exception as e:
        print(f"確認ボタンなし: {e}")
        dump_buttons(drv, "確認探索")
        with open("D:/yoyaku/debug_step4.html", "w", encoding="utf-8") as f:
            f.write(drv.page_source)
        drv.quit(); return

    print("\n=== STEP5: 予約申込へ ===")
    try:
        res_btn = WebDriverWait(drv, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'予約申込へ')]"))
        )
        print(f"予約申込ボタン: {res_btn.text!r}")
        drv.execute_script("arguments[0].click();", res_btn)
        time.sleep(2)
        print(f"URL: {drv.current_url}")
    except Exception as e:
        print(f"予約申込ボタンなし: {e}")
        dump_buttons(drv, "申込探索")
        with open("D:/yoyaku/debug_step5.html", "w", encoding="utf-8") as f:
            f.write(drv.page_source)
        drv.quit(); return

    print("\n=== STEP6: 利用人数入力 ===")
    try:
        pbox = WebDriverWait(drv, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='text']"))
        )
        pbox.clear()
        pbox.send_keys("16")
        print("16入力完了")
        time.sleep(0.5)
    except Exception as e:
        print(f"人数入力欄なし: {e}")
        inputs = drv.find_elements(By.TAG_NAME, "input")
        for i in inputs:
            print(f"  type={i.get_attribute('type')!r} name={i.get_attribute('name')!r}")
        drv.quit(); return

    print("\n=== STEP7: 支払方法へ ===")
    try:
        pay = WebDriverWait(drv, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//span[contains(.,'支払方法へ')]"))
        )
        drv.execute_script("arguments[0].click();", pay)
        print("支払方法へクリック")
        time.sleep(2)

        # 再表示チェック
        try:
            pay2 = WebDriverWait(drv, 3).until(
                EC.element_to_be_clickable((By.XPATH, "//span[contains(.,'支払方法へ')]"))
            )
            drv.execute_script("arguments[0].click();", pay2)
            print("支払方法へ再クリック")
            time.sleep(2)
        except: pass

        print(f"URL: {drv.current_url}")
        print(f"タイトル: {drv.title}")
    except Exception as e:
        print(f"支払方法ボタンなし: {e}")
        dump_buttons(drv, "支払探索")
        drv.quit(); return

    # ---- 最終確認 ----
    pay_elems = drv.find_elements(By.XPATH, "//*[contains(text(),'支払方法')]")
    if pay_elems:
        print("\n✓✓✓ 予約フロー完全成功！支払方法ページに到達 ✓✓✓")
        send_discord("【テスト成功】予約フロー完了！支払方法ページに到達しました。本番運用可能です。")
    else:
        print(f"\n現在URL: {drv.current_url}")
        print("支払方法ページ未到達")
        send_discord(f"【要確認】支払方法ページ到達できず。URL: {drv.current_url}")

    with open("D:/yoyaku/debug_final.html", "w", encoding="utf-8") as f:
        f.write(drv.page_source)
    print("HTML保存: debug_final.html")

    drv.quit()
    print("=== 完了 ===")

if __name__ == "__main__":
    main()
