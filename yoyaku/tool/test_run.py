# -*- coding: utf-8 -*-
"""
テスト実行スクリプト: ログイン→空き確認→予約 を1サイクル実行
"""
import sys
import queue
import threading
from reserve_core import ReserveWorker, load_config, get_time_slots

def main():
    cfg = load_config()
    if not cfg.get("user_id") or not cfg.get("password"):
        print("[Error] config.json にログインID/パスワードが設定されていません")
        sys.exit(1)

    print(f"=== テスト実行 ===")
    print(f"  対象日付: {cfg['target_date']}")
    print(f"  ログインID: {cfg['user_id']}")
    print(f"  利用目的: {cfg.get('purpose', 'バレーボール')}")
    print(f"  利用人数: {cfg.get('num_people', 10)}")
    print(f"  時間帯優先: {get_time_slots(cfg['target_date'])}")
    print()

    log_q = queue.Queue()
    stop_ev = threading.Event()

    # ログをリアルタイム表示するスレッド
    def log_printer():
        while not stop_ev.is_set() or not log_q.empty():
            try:
                msg = log_q.get(timeout=0.5)
                print(msg, flush=True)
            except queue.Empty:
                continue

    printer = threading.Thread(target=log_printer, daemon=True)
    printer.start()

    worker = ReserveWorker(cfg, log_q, stop_ev)

    try:
        worker.run()
    except KeyboardInterrupt:
        print("\n[Info] Ctrl+C で中断しました")
        stop_ev.set()
    except Exception as e:
        print(f"\n[Error] 予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
    finally:
        stop_ev.set()
        printer.join(timeout=3)
        try:
            if worker.driver:
                worker.driver.quit()
        except Exception:
            pass

if __name__ == "__main__":
    main()
