# -*- coding: utf-8 -*-
"""
札幌市 体育館 自動予約ツール - Webサーバー版
使い方: python web_app.py
ブラウザで http://localhost:5000 を開く（スマホでも同じLAN内からアクセス可能）
"""

import os
import hmac
import time
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


# ==========================
# ログイン試行回数の制限（総当たり対策）
# ngrok等で外部公開する際、PINだけが防御になるため必須。
# プロセス内メモリで管理（再起動でリセット）。
# ==========================

_MAX_ATTEMPTS = 5          # この回数連続で失敗したらロック
_LOCK_SECONDS = 300        # ロック時間（秒）
_login_attempts = {}       # {ip: [失敗回数, ロック解除時刻]}
_attempts_lock = threading.Lock()


def _client_ip() -> str:
    # ngrok/リバースプロキシ経由では X-Forwarded-For に実IPが入る
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _check_locked(ip: str):
    """ロック中なら残り秒数を返す。ロックされていなければ None。"""
    with _attempts_lock:
        entry = _login_attempts.get(ip)
        if not entry:
            return None
        count, until = entry
        remain = until - time.time()
        if remain > 0:
            return int(remain)
        if count >= _MAX_ATTEMPTS:
            # ロック期限切れ → カウンタをリセット
            _login_attempts.pop(ip, None)
        return None


def _record_failure(ip: str):
    with _attempts_lock:
        count, _ = _login_attempts.get(ip, (0, 0.0))
        count += 1
        until = time.time() + _LOCK_SECONDS if count >= _MAX_ATTEMPTS else 0.0
        _login_attempts[ip] = (count, until)
        return count


def _clear_failures(ip: str):
    with _attempts_lock:
        _login_attempts.pop(ip, None)


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True) or {}
    pin = str(data.get("pin", "")).strip()
    correct = _get_web_pin()
    if not correct:
        # PIN未設定ならログイン不要
        session["logged_in"] = True
        return jsonify({"ok": True})

    ip = _client_ip()
    locked = _check_locked(ip)
    if locked is not None:
        return jsonify({
            "ok": False,
            "error": f"試行回数が多すぎます。{locked // 60 + 1}分後に再試行してください",
        }), 429

    # 桁数差から情報が漏れないよう定数時間で比較
    if hmac.compare_digest(pin, correct):
        _clear_failures(ip)
        session["logged_in"] = True
        session.permanent = True
        return jsonify({"ok": True})

    count = _record_failure(ip)
    print(f"[Warn] PIN認証失敗 ({count}回目) from {ip}")
    if count >= _MAX_ATTEMPTS:
        return jsonify({
            "ok": False,
            "error": f"試行回数が多すぎます。{_LOCK_SECONDS // 60}分間ロックされました",
        }), 429
    return jsonify({
        "ok": False,
        "error": f"PINが違います（あと{_MAX_ATTEMPTS - count}回で{_LOCK_SECONDS // 60}分間ロック）",
    }), 401


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
        "interval_sec": int(data.get("interval_sec", 1)),
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
