# -*- coding: utf-8 -*-
"""
空きのある日付を探すスクリプト
3/10〜3/31 の範囲で空きがある日を探す
"""
import sys
import time
import datetime
import queue
import threading
from reserve_core import ReserveWorker, load_config, get_time_slots

def main():
    cfg = load_config()
    log_q = queue.Queue()
    stop_ev = threading.Event()

    def drain_log():
        while True:
            try:
                msg = log_q.get_nowait()
                print(msg, flush=True)
            except queue.Empty:
                break

    worker = ReserveWorker(cfg, log_q, stop_ev)

    try:
        worker.driver = worker.build_driver()
        worker.login()
        drain_log()
    except Exception as e:
        drain_log()
        print(f"[Error] ログイン失敗: {e}")
        sys.exit(1)

    # 3/10〜3/31 で空きを探す
    today = datetime.date(2026, 3, 10)
    end = datetime.date(2026, 3, 31)
    found_dates = []

    d = today
    while d <= end:
        date_str = d.isoformat()
        target_url = (
            f"https://yoyaku.harp.lg.jp/sapporo/FacilitySearch/Index/"
            f"?u%5B0%5D=70&ud={date_str}"
        )
        worker.driver.get(target_url)
        worker.wait_render()
        drain_log()

        available = worker.collect_available()
        names = [name for name, _, _ in available]
        day_name = ["月","火","水","木","金","土","日"][d.weekday()]
        print(f"  {date_str}（{day_name}）: 空き {len(names)}件 {names[:3]}{'...' if len(names)>3 else ''}", flush=True)

        if names:
            found_dates.append((date_str, names))

        d += datetime.timedelta(days=1)
        time.sleep(0.5)

    print(f"\n=== 結果 ===")
    if found_dates:
        for date_str, names in found_dates:
            print(f"  {date_str}: {names}")
    else:
        print("  空きのある日付はありませんでした")

    worker.driver.quit()

if __name__ == "__main__":
    main()
