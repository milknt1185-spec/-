# -*- coding: utf-8 -*-
"""
アクセスPIN設定ツール
使い方: python set_pin.py
"""

import re
from reserve_core import load_config, save_config


def main():
    print("=" * 40)
    print("  予約ツール - アクセスPIN設定")
    print("=" * 40)
    print()

    cfg = load_config()
    current_pin = cfg.get("web_pin", "")
    if current_pin:
        print(f"現在のPIN: {'*' * len(current_pin)} ({len(current_pin)}桁)")
    else:
        print("現在のPIN: 未設定（認証なし）")

    print()
    print("新しいPINを入力してください（4〜8桁の数字）")
    print("空のままEnterでPINを削除（認証なし）")
    print()

    while True:
        pin = input("新しいPIN > ").strip()

        if pin == "":
            cfg.pop("web_pin", None)
            save_config(cfg)
            print()
            print("[OK] PINを削除しました（認証なし）")
            break

        if not re.fullmatch(r"\d{4,8}", pin):
            print("[Error] 4〜8桁の数字で入力してください")
            continue

        cfg["web_pin"] = pin
        save_config(cfg)
        print()
        print(f"[OK] PINを設定しました: {'*' * len(pin)} ({len(pin)}桁)")
        print()
        print("スマホでアクセスした際にこのPINを入力してログインします。")
        break

    print()
    print("web_app.py を起動してください: python web_app.py")


if __name__ == "__main__":
    main()
