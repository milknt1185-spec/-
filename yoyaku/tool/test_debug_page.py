# -*- coding: utf-8 -*-
"""
ページ構造デバッグ: 実際のHTML要素を確認する
"""
import sys
import time
import queue
import threading
from reserve_core import ReserveWorker, load_config
from selenium.webdriver.common.by import By

def main():
    cfg = load_config()
    log_q = queue.Queue()
    stop_ev = threading.Event()

    def drain():
        while True:
            try:
                print(log_q.get_nowait(), flush=True)
            except queue.Empty:
                break

    worker = ReserveWorker(cfg, log_q, stop_ev)
    worker.driver = worker.build_driver()
    worker.login()
    drain()

    # --- 4月の日付を探す ---
    test_dates = ["2026-04-06", "2026-04-07", "2026-04-13", "2026-04-14", "2026-04-20"]
    for date_str in test_dates:
        url = f"https://yoyaku.harp.lg.jp/sapporo/FacilitySearch/Index/?u%5B0%5D=70&ud={date_str}"
        worker.driver.get(url)
        worker.wait_render()
        drain()

        available = worker.collect_available()
        names = [n for n, _, _ in available]
        print(f"\n  {date_str}: 空き {len(names)}件 {names[:5]}", flush=True)

    # --- 最後のページの構造をダンプ ---
    print("\n=== ページ構造デバッグ ===", flush=True)

    # facility- 要素
    elems = worker.driver.find_elements(By.CSS_SELECTOR, "span[id^='facility']")
    print(f"  facility* 要素数: {len(elems)}", flush=True)
    for e in elems[:10]:
        print(f"    id={e.get_attribute('id')!r}  text={e.text!r}  y={e.location['y']}", flush=True)

    # 境界テキスト
    boundaries = worker.driver.find_elements(By.XPATH, "//span[contains(text(),'以下は希望日時に予約できません')]")
    print(f"  境界テキスト要素数: {len(boundaries)}", flush=True)
    for b in boundaries:
        print(f"    text={b.text!r}  y={b.location['y']}", flush=True)

    # group- 要素
    groups = worker.driver.find_elements(By.CSS_SELECTOR, "div[id^='group-']")
    print(f"  group- 要素数: {len(groups)}", flush=True)

    # ページタイトル・現在URL
    print(f"  URL: {worker.driver.current_url}", flush=True)
    print(f"  title: {worker.driver.title}", flush=True)

    # ページ内テキストの一部
    body = worker.driver.find_element(By.TAG_NAME, "body").text
    # 最初の500文字
    print(f"\n  body text (先頭500文字):", flush=True)
    print(f"  {body[:500]}", flush=True)

    worker.driver.quit()

if __name__ == "__main__":
    main()
