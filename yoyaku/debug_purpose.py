# -*- coding: utf-8 -*-
"""
内容入力ページの利用目的ドロップダウンの構造を詳細確認
"""
import time, datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

LOGIN_URL   = "https://yoyaku.harp.lg.jp/sapporo/Login"
USER_ID     = "00157875"
PASSWORD    = "kankyou5623"
AVAIL_URL   = "https://yoyaku.harp.lg.jp/sapporo/FacilityAvailability/Index/011002/0258?ptn=1&d=2026-02-18"
TARGET_DATE = "2026-02-18"

def build_driver():
    options = Options()
    options.add_argument("--window-size=1500,1200")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()), options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"})
    return driver

def login(driver):
    driver.get(LOGIN_URL)
    time.sleep(3)
    wait = WebDriverWait(driver, 15)
    wait.until(EC.presence_of_element_located((By.NAME, "userId"))).send_keys(USER_ID)
    driver.find_element(By.NAME, "password").send_keys(PASSWORD)
    btn = wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//button[.//span[contains(text(),'ログイン')]]")))
    driver.execute_script("arguments[0].click();", btn)
    WebDriverWait(driver, 10).until(lambda d: "/Login" not in d.current_url)
    print("[OK] ログイン完了")

def go_to_input_page(driver):
    driver.get(AVAIL_URL)
    time.sleep(3)
    try:
        skip = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.XPATH, "//span[contains(text(),'スキップ')]")))
        driver.execute_script("arguments[0].click();", skip)
        time.sleep(1)
    except Exception:
        pass

    date = datetime.date.fromisoformat(TARGET_DATE)
    date_xpath = f"//button[contains(@title,'{date.month}月{date.day}日') and contains(@title,'利用可能')]"
    try:
        date_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, date_xpath)))
        driver.execute_script("arguments[0].click();", date_btn)
        print("[OK] 日付クリック")
        time.sleep(2)
    except Exception as e:
        print(f"[Warn] 日付クリック失敗: {e}")

    for title in ["19時15分から21時45分 利用可能", "17時45分から21時45分 利用可能"]:
        try:
            btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, f"//button[contains(@title,'{title}')]")))
            driver.execute_script("arguments[0].click();", btn)
            print(f"[OK] 時間帯: {title}")
            time.sleep(1)
            break
        except Exception:
            continue

    confirm = WebDriverWait(driver, 5).until(
        EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'確認')]")))
    driver.execute_script("arguments[0].click();", confirm)
    print("[OK] 確認")
    time.sleep(1)

    reserve_btn = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'予約申込へ')]")))
    driver.execute_script("arguments[0].click();", reserve_btn)
    print("[OK] 予約申込へ")
    time.sleep(3)
    print(f"URL: {driver.current_url}")

def main():
    driver = build_driver()
    try:
        login(driver)
        go_to_input_page(driver)

        # === STEP1: ドロップダウンを開く前の状態確認 ===
        print("\n=== ドロップダウンを開く前 ===")
        text_inputs = driver.find_elements(By.XPATH, "//input[@type='text']")
        for i, inp in enumerate(text_inputs):
            print(f"  input[{i}] id={inp.get_attribute('id')!r} "
                  f"placeholder={inp.get_attribute('placeholder')!r}")

        # === STEP2: 利用目的ドロップダウンをクリックして開く ===
        print("\n=== 利用目的ドロップダウンをクリック ===")
        purpose_input = text_inputs[0]
        driver.execute_script("arguments[0].scrollIntoView(true);", purpose_input)
        driver.execute_script("arguments[0].click();", purpose_input)
        time.sleep(1.5)

        # === STEP3: ドロップダウン内の全要素を確認 ===
        print("\n=== ドロップダウン内アイテム（v-list-item__title） ===")
        items = driver.find_elements(By.XPATH, "//div[contains(@class,'v-list-item__title')]")
        for i, item in enumerate(items):
            cls = item.get_attribute("class") or ""
            txt = item.text
            parent_cls = driver.execute_script(
                "return arguments[0].parentNode ? arguments[0].parentNode.className : '';", item)
            print(f"  [{i:2}] text={txt!r:30} parentClass={parent_cls[:60]!r}")

        print("\n=== v-list-item（リンク形式） ===")
        list_items = driver.find_elements(By.XPATH,
            "//div[contains(@class,'v-list-item--link')]")
        for i, item in enumerate(list_items):
            print(f"  [{i:2}] text={item.text[:50]!r} class={item.get_attribute('class')[:60]!r}")

        print("\n=== メニュー/オーバーレイコンテンツ ===")
        menu_contents = driver.find_elements(By.XPATH,
            "//div[contains(@class,'v-menu__content')]")
        for i, mc in enumerate(menu_contents):
            print(f"  menu[{i}] display={driver.execute_script('return window.getComputedStyle(arguments[0]).display',mc)!r}")
            children = mc.find_elements(By.XPATH, ".//*")
            for j, child in enumerate(children[:20]):
                if child.text.strip():
                    print(f"    [{j}] tag={child.tag_name} class={child.get_attribute('class')[:40]!r} text={child.text[:40]!r}")

        print("\n\n>>> 'バレーボール' を含む要素 <<<")
        volley = driver.find_elements(By.XPATH, "//*[contains(text(),'バレーボール')]")
        for i, e in enumerate(volley):
            print(f"  [{i}] tag={e.tag_name} class={e.get_attribute('class')[:50]!r} text={e.text!r}")

        print("\n>>> '学校開放' を含む要素 <<<")
        gakko = driver.find_elements(By.XPATH, "//*[contains(text(),'学校開放')]")
        for i, e in enumerate(gakko):
            print(f"  [{i}] tag={e.tag_name} class={e.get_attribute('class')[:50]!r} text={e.text!r}")

        # === STEP4: 学校開放があればクリックして次の階層を確認 ===
        if gakko:
            print(f"\n=== 「学校開放」をクリックします ===")
            driver.execute_script("arguments[0].scrollIntoView(true);", gakko[0])
            driver.execute_script("arguments[0].click();", gakko[0])
            time.sleep(1.5)

            print("=== クリック後の v-list-item__title ===")
            items2 = driver.find_elements(By.XPATH, "//div[contains(@class,'v-list-item__title')]")
            for i, item in enumerate(items2):
                print(f"  [{i:2}] text={item.text!r}")

            print("\n>>> クリック後の 'バレーボール' を含む要素 <<<")
            volley2 = driver.find_elements(By.XPATH, "//*[contains(text(),'バレーボール')]")
            for i, e in enumerate(volley2):
                print(f"  [{i}] tag={e.tag_name} class={e.get_attribute('class')[:50]!r} text={e.text!r}")

        print("\n=== 調査完了（5秒後に終了） ===")
        time.sleep(5)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
