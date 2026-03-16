# -*- coding: utf-8 -*-
"""
札幌市 体育館 自動予約ツール - Webサーバー版
使い方: python web_app.py
ブラウザで http://localhost:5000 を開く（スマホでも同じLAN内からアクセス可能）
"""

import os
import queue
import threading
import datetime
from functools import wraps

from flask import Flask, jsonify, request, render_template, session, redirect, url_for

from reserve_core import ReserveWorker, load_config, save_config

app = Flask(__name__)

# ==========================
# シークレットキー（セッション管理用）
# 初回起動時に自動生成して .secret_key に保存
# ==========================

_SECRET_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret_key")

def _load_or_create_secret_key() -> bytes:
    if os.path.exists(_SECRET_KEY_FILE):
        with open(_SECRET_KEY_FILE, "rb") as f:
            key = f.read().strip()
            if key:
                return key
    key = os.urandom(32)
    with open(_SECRET_KEY_FILE, "wb") as f:
        f.write(key)
    return key

app.secret_key = _load_or_create_secret_key()


# ==========================
# 認証
# ==========================

def _get_web_pin() -> str:
    cfg = load_config()
    return str(cfg.get("web_pin", ""))

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        pin = _get_web_pin()
        # web_pin が未設定（空）なら認証スキップ
        if not pin:
            return f(*args, **kwargs)
        if not session.get("logged_in"):
            # APIなら 401、ページなら login にリダイレクト
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "ログインが必要です"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET"])
def login_page():
    if session.get("logged_in"):
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True) or {}
    pin = str(data.get("pin", "")).strip()
    correct = _get_web_pin()
    if not correct:
        # PIN未設定ならログイン不要
        session["logged_in"] = True
        return jsonify({"ok": True})
    if pin == correct:
        session["logged_in"] = True
        session.permanent = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "PINが違います"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


# ==========================
# ジョブ状態管理
# ==========================

class JobState:
    def __init__(self):
        self._lock = threading.Lock()
        self.running = False
        self._stop_event = threading.Event()
        self._log_queue: queue.Queue = queue.Queue()
        self._logs: list[str] = []
        self._worker_thread: threading.Thread | None = None

    def start(self, config: dict) -> bool:
        with self._lock:
            if self.running:
                return False
            self._stop_event = threading.Event()
            self._log_queue = queue.Queue()
            self._logs = []
            worker = ReserveWorker(config, self._log_queue, self._stop_event)
            self._worker_thread = threading.Thread(
                target=self._run_worker, args=(worker,), daemon=True
            )
            self._worker_thread.start()
            self.running = True
            return True

    def stop(self):
        with self._lock:
            self._stop_event.set()
            self.running = False

    def _run_worker(self, worker: ReserveWorker):
        try:
            worker.run()
        finally:
            with self._lock:
                self.running = False

    def drain_logs(self):
        while True:
            try:
                msg = self._log_queue.get_nowait()
                self._logs.append(msg)
            except queue.Empty:
                break

    def get_logs(self, since: int = 0) -> list[str]:
        self.drain_logs()
        return self._logs[since:]

    def log_count(self) -> int:
        self.drain_logs()
        return len(self._logs)


_job = JobState()


# ==========================
# API
# ==========================

@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/api/status")
@login_required
def api_status():
    return jsonify({
        "running": _job.running,
        "log_count": _job.log_count(),
    })


@app.route("/api/logs")
@login_required
def api_logs():
    since = request.args.get("since", 0, type=int)
    logs = _job.get_logs(since)
    return jsonify({
        "logs": logs,
        "total": _job.log_count(),
    })


@app.route("/api/config", methods=["GET"])
@login_required
def api_config_get():
    cfg = load_config()
    cfg.pop("password", None)
    cfg.pop("web_pin", None)
    return jsonify(cfg)


@app.route("/api/start", methods=["POST"])
@login_required
def api_start():
    if _job.running:
        return jsonify({"ok": False, "error": "既に実行中です"}), 400

    data = request.get_json(force=True) or {}

    date_str = data.get("target_date", "")
    try:
        datetime.date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"ok": False, "error": "日付が不正です（YYYY-MM-DD）"}), 400

    if not data.get("user_id"):
        return jsonify({"ok": False, "error": "ログインIDが空です"}), 400
    if not data.get("password"):
        return jsonify({"ok": False, "error": "パスワードが空です"}), 400

    config = {
        "target_date": date_str,
        "user_id": data["user_id"],
        "password": data["password"],
        "purpose": data.get("purpose", "バレーボール"),
        "num_people": int(data.get("num_people", 16)),
        "discord_webhook": data.get("discord_webhook", ""),
        "interval_sec": max(5, int(data.get("interval_sec", 5))),
    }
    save_config(config)
    _job.start(config)
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
@login_required
def api_stop():
    _job.stop()
    return jsonify({"ok": True})


# ==========================
# エントリーポイント
# ==========================

if __name__ == "__main__":
    pin = _get_web_pin()
    if pin:
        print(f"[Info] アクセスPIN保護が有効です（PIN: {pin}）")
    else:
        print("[Info] PIN未設定 - 認証なし。set_pin.py でPINを設定できます")
    print("[Info] サーバー起動: http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
