# -*- coding: utf-8 -*-
"""
札幌市 体育館 自動予約ツール - GUIアプリ版
使い方: python auto_reserve_gui.py
"""

import os
import queue
import datetime
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from reserve_core import ReserveWorker, load_config, save_config, CONFIG_FILE


# ==========================
# GUI
# ==========================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("札幌市 体育館 自動予約ツール")
        self.resizable(False, False)
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._log_queue: queue.Queue = queue.Queue()
        self._saved = load_config()
        self._build_ui()
        self._poll_log()

    # ---------- UI構築 ----------

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # ---- 設定フレーム ----
        frm_cfg = ttk.LabelFrame(self, text="設定", padding=8)
        frm_cfg.grid(row=0, column=0, sticky="ew", **pad)

        s = self._saved  # 保存済み設定ショートカット

        # 日付
        ttk.Label(frm_cfg, text="予約日 (YYYY-MM-DD)").grid(row=0, column=0, sticky="w")
        self.var_date = tk.StringVar(value=s.get("target_date", str(datetime.date.today())))
        e_date = ttk.Entry(frm_cfg, textvariable=self.var_date, width=14)
        e_date.grid(row=0, column=1, sticky="w", padx=4)
        e_date.bind("<FocusOut>", lambda _: self._autosave())

        # ログインID
        ttk.Label(frm_cfg, text="ログインID").grid(row=1, column=0, sticky="w")
        self.var_uid = tk.StringVar(value=s.get("user_id", os.getenv("SAPPORO_ID", "")))
        e_uid = ttk.Entry(frm_cfg, textvariable=self.var_uid, width=20)
        e_uid.grid(row=1, column=1, sticky="w", padx=4)
        e_uid.bind("<FocusOut>", lambda _: self._autosave())

        # パスワード
        ttk.Label(frm_cfg, text="パスワード").grid(row=2, column=0, sticky="w")
        self.var_pw = tk.StringVar(value=s.get("password", os.getenv("SAPPORO_PW", "")))
        e_pw = ttk.Entry(frm_cfg, textvariable=self.var_pw, width=20, show="*")
        e_pw.grid(row=2, column=1, sticky="w", padx=4)
        e_pw.bind("<FocusOut>", lambda _: self._autosave())

        # 利用目的
        ttk.Label(frm_cfg, text="利用目的（スポーツ名）").grid(row=3, column=0, sticky="w")
        self.var_purpose = tk.StringVar(value=s.get("purpose", "バレーボール"))
        e_purpose = ttk.Entry(frm_cfg, textvariable=self.var_purpose, width=20)
        e_purpose.grid(row=3, column=1, sticky="w", padx=4)
        e_purpose.bind("<FocusOut>", lambda _: self._autosave())

        # 利用人数
        ttk.Label(frm_cfg, text="利用人数").grid(row=4, column=0, sticky="w")
        self.var_people = tk.IntVar(value=s.get("num_people", 16))
        ttk.Spinbox(frm_cfg, textvariable=self.var_people, from_=1, to=100, width=6,
                    command=self._autosave).grid(row=4, column=1, sticky="w", padx=4)

        # Discord Webhook
        ttk.Label(frm_cfg, text="Discord Webhook URL").grid(row=5, column=0, sticky="w")
        self.var_discord = tk.StringVar(value=s.get("discord_webhook", ""))
        e_discord = ttk.Entry(frm_cfg, textvariable=self.var_discord, width=60)
        e_discord.grid(row=5, column=1, sticky="w", padx=4)
        e_discord.bind("<FocusOut>", lambda _: self._autosave())

        # 監視間隔
        ttk.Label(frm_cfg, text="監視間隔 (秒)").grid(row=6, column=0, sticky="w")
        self.var_interval = tk.IntVar(value=s.get("interval_sec", 1))
        ttk.Spinbox(frm_cfg, textvariable=self.var_interval, from_=1, to=60, width=6,
                    command=self._autosave).grid(row=6, column=1, sticky="w", padx=4)

        # ---- ボタンフレーム ----
        frm_btn = ttk.Frame(self, padding=4)
        frm_btn.grid(row=1, column=0, sticky="ew", **pad)

        self.btn_start = ttk.Button(frm_btn, text="▶  監視開始", command=self._on_start)
        self.btn_start.pack(side="left", padx=4)

        self.btn_stop = ttk.Button(frm_btn, text="■  停止", command=self._on_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=4)

        self.btn_clear = ttk.Button(frm_btn, text="ログクリア", command=self._on_clear)
        self.btn_clear.pack(side="right", padx=4)

        # ---- ステータスラベル ----
        self.lbl_status = ttk.Label(frm_btn, text="待機中", foreground="gray")
        self.lbl_status.pack(side="left", padx=8)

        # ---- ログエリア ----
        frm_log = ttk.LabelFrame(self, text="ログ", padding=4)
        frm_log.grid(row=2, column=0, sticky="nsew", **pad)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self.txt_log = tk.Text(frm_log, width=80, height=22, state="disabled",
                               font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
                               insertbackground="white")
        sb = ttk.Scrollbar(frm_log, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=sb.set)
        self.txt_log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ---------- 自動保存 ----------

    def _autosave(self):
        """フィールドから外れるたびに現在の入力値を config.json へ保存"""
        try:
            cfg = {
                "target_date":    self.var_date.get().strip(),
                "user_id":        self.var_uid.get().strip(),
                "password":       self.var_pw.get(),          # 空でも保存
                "purpose":        self.var_purpose.get().strip(),
                "num_people":     self.var_people.get(),
                "discord_webhook": self.var_discord.get().strip(),
                "interval_sec":   self.var_interval.get(),
            }
            save_config(cfg)
        except Exception:
            pass  # 起動直後など IntVar 未確定時は無視

    # ---------- イベント ----------

    def _on_start(self):
        date_str = self.var_date.get().strip()
        try:
            datetime.date.fromisoformat(date_str)
        except ValueError:
            messagebox.showerror("エラー", "日付の形式が不正です。YYYY-MM-DD で入力してください。")
            return

        if not self.var_uid.get().strip():
            messagebox.showerror("エラー", "ログインIDを入力してください。")
            return
        if not self.var_pw.get().strip():
            messagebox.showerror("エラー", "パスワードを入力してください。")
            return

        config = {
            "target_date": date_str,
            "user_id": self.var_uid.get().strip(),
            "password": self.var_pw.get().strip(),
            "purpose": self.var_purpose.get().strip(),
            "num_people": self.var_people.get(),
            "discord_webhook": self.var_discord.get().strip(),
            "interval_sec": self.var_interval.get(),
        }
        save_config(config)  # 設定を config.json に保存

        self._stop_event = threading.Event()
        worker = ReserveWorker(config, self._log_queue, self._stop_event)

        self._worker_thread = threading.Thread(target=worker.run, daemon=True)
        self._worker_thread.start()

        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.lbl_status.configure(text="監視中...", foreground="green")

    def _on_stop(self):
        self._stop_event.set()
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.lbl_status.configure(text="停止中...", foreground="orange")

    def _on_clear(self):
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    # ---------- ログポーリング ----------

    def _poll_log(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self.txt_log.configure(state="normal")
                self.txt_log.insert("end", msg + "\n")
                self.txt_log.see("end")
                self.txt_log.configure(state="disabled")

                if "[END]" in msg:
                    self.btn_start.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                    self.lbl_status.configure(text="予約完了！", foreground="blue")
                elif "監視を停止しました" in msg:
                    self.lbl_status.configure(text="待機中", foreground="gray")

        except queue.Empty:
            pass

        self.after(200, self._poll_log)

    # ---------- 終了処理 ----------

    def on_close(self):
        self._autosave()          # 閉じる前に現在の入力値を保存
        self._stop_event.set()
        self.destroy()


# ==========================
# エントリーポイント
# ==========================

if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
