# -*- coding: utf-8 -*-
"""
札幌市 体育館 自動予約ツール - コアロジック
GUI版・Web版の両方から共有するモジュール
"""

import os
import json
import time
import queue
import datetime
import threading
import traceback
from typing import Set, List, Tuple

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# ==========================
# 設定ファイルパス
# ==========================

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(config: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ==========================
# 祝日判定
# ==========================

def is_holiday_jp(date: datetime.date) -> bool:
    try:
        import jpholiday
        return jpholiday.is_holiday(date)
    except ImportError:
        return False


def get_time_slots(date_str: str) -> List[str]:
    date = datetime.date.fromisoformat(date_str)
    weekday = date.weekday()
    is_weekend = weekday >= 5
    is_hol = is_holiday_jp(date)

    if is_weekend or is_hol:
        return [
            "17時45分から21時45分 利用可能",
            "19時15分から21時45分 利用可能",
        ]
    else:
        return [
            "19時15分から21時45分 利用可能",
            "17時45分から21時45分 利用可能",
        ]


# ==========================
# 予約ロジック（スレッド内で実行）
# ==========================

class ReserveWorker:
    LOGIN_URL = "https://yoyaku.harp.lg.jp/sapporo/Login"

    # サイトの実際の構造:
    #   空きあり施設: <span id="facility-011002-0258">屯田北中学校</span>  ← facility- (数字なし)
    #   空きなし施設: <span id="facility2-011002-0203">山鼻小学校</span>   ← facility2-
    #   境界テキスト「以下は希望日時に予約できません。」より上 = 空きあり
    #   → 空きあり施設だけを確実に取るには facility- だがfacility2- も含まれるため
    #     境界テキストのY座標より上にある facility- 要素を空きありとする
    BOUNDARY_XPATH = "//span[contains(text(),'以下は希望日時に予約できません。')]"
    FACILITY_CSS = "span[id^='facility-']"   # facility- と facility2- 両方マッチ
    GROUP_CSS = "div[id^='group-']"
    RENDER_TIMEOUT = 5

    def __init__(self, config: dict, log_queue: queue.Queue, stop_event: threading.Event):
        self.config = config
        self.log_queue = log_queue
        self.stop_event = stop_event
        self.driver = None

    def log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(f"[{ts}] {msg}")

    # ---------- Discord ----------

    def send_discord(self, msg: str):
        url = self.config["discord_webhook"]
        if not url:
            return
        try:
            r = requests.post(url, json={"content": msg}, timeout=10)
            if r.status_code != 204:
                self.log(f"[Warn] Discord通知失敗: {r.status_code}")
            else:
                self.log(f"[OK] Discord通知送信")
        except Exception as e:
            self.log(f"[Error] Discord通知エラー: {e}")

    def send_discord_lines(self, lines: List[str]):
        # 空き検出通知は送信しない（予約完了時のみ通知）
        pass

    # ---------- Driver ----------

    def build_driver(self):
        options = Options()
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1500,1200")

        # Bot検出回避
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )

        # Chrome/ChromeDriverのパスを固定（Linux環境用）
        _CHROME_BIN = "/opt/chrome-145/chrome"
        _CHROMEDRIVER_BIN = "/opt/chrome-145/chromedriver"
        import os as _os
        if _os.path.exists(_CHROME_BIN):
            options.binary_location = _CHROME_BIN
            service = ChromeService(_CHROMEDRIVER_BIN)
        else:
            service = ChromeService(ChromeDriverManager().install())

        # ヘッドレスモード（GUIなし環境用）
        if not _os.environ.get("DISPLAY"):
            options.add_argument("--headless=new")

        driver = webdriver.Chrome(
            service=service,
            options=options
        )

        # navigator.webdriver を隠す
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.navigator.chrome = {runtime: {}};
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['ja-JP', 'ja', 'en-US', 'en']});
                """
            },
        )

        return driver

    # ---------- ログイン ----------

    def login(self):
        wait = WebDriverWait(self.driver, 15)
        self.driver.get(self.LOGIN_URL)
        time.sleep(3)

        # Incapsula チャレンジが出る場合はそのまま待機（リトライは1回のみ）
        if "Incapsula" in self.driver.page_source or "main-iframe" in self.driver.page_source:
            self.log("[Info] セキュリティチェック待機中（最大15秒）...")
            time.sleep(15)
            # まだブロックされている場合だけ再取得
            if "Incapsula" in self.driver.page_source:
                self.driver.get(self.LOGIN_URL)
                time.sleep(5)

        # userId フィールドが出るまで待つ
        user_box = wait.until(EC.presence_of_element_located((By.NAME, "userId")))
        pass_box = wait.until(EC.presence_of_element_located((By.NAME, "password")))

        user_box.clear()
        user_box.send_keys(self.config["user_id"])
        pass_box.clear()
        pass_box.send_keys(self.config["password"])

        login_btn = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[.//span[contains(text(),'ログイン')]]")
            )
        )
        self.driver.execute_script("arguments[0].click();", login_btn)

        # ログインページから離れるまで待つ（最大10秒）
        try:
            WebDriverWait(self.driver, 10).until(
                lambda d: "/Login" not in d.current_url
            )
        except Exception:
            pass

        time.sleep(1)

        # ログイン失敗判定: まだ /Login にいる場合のみ失敗
        if "/Login" in self.driver.current_url:
            raise RuntimeError("ログイン失敗。IDまたはパスワードを確認してください。")

        self.log(f"[OK] ログイン完了 → {self.driver.current_url}")

    # ---------- 描画待ち ----------

    def wait_render(self):
        """facility- または facility2- 要素、もしくは境界テキストが表示されるまで待つ"""
        try:
            WebDriverWait(self.driver, self.RENDER_TIMEOUT).until(
                lambda d: (
                    d.find_elements(By.CSS_SELECTOR, "span[id^='facility']")
                    or d.find_elements(By.XPATH, self.BOUNDARY_XPATH)
                )
            )
        except Exception:
            self.log("[Warn] 施設リストの読み込みがタイムアウトしました")

    # ---------- 空き収集 ----------

    # JavaScript一括収集: Seleniumの要素ごとHTTP往復を全廃
    _JS_COLLECT = """
    var boundaryY = Infinity;
    var spans = document.querySelectorAll('span');
    for (var i = 0; i < spans.length; i++) {
        if (spans[i].textContent.indexOf('以下は希望日時に予約できません') !== -1) {
            boundaryY = spans[i].getBoundingClientRect().top + window.scrollY;
            break;
        }
    }
    var elems = document.querySelectorAll("span[id^='facility-']");
    var result = [];
    for (var j = 0; j < elems.length; j++) {
        var e = elems[j];
        var id = e.id;
        if (id.indexOf('facility2-') === 0) continue;
        var y = e.getBoundingClientRect().top + window.scrollY;
        if (y >= boundaryY) continue;
        var text = e.textContent.trim();
        if (!text) continue;
        var parts = id.split('-');
        if (parts.length >= 3) result.push([text, parts[1], parts[2]]);
    }
    return result;
    """

    def collect_available(self) -> List[Tuple[str, str, str]]:
        """空きあり施設の (名前, lgc, fc) をJavaScript一括で取得（高速）"""
        raw = self.driver.execute_script(self._JS_COLLECT)
        return [(r[0], r[1], r[2]) for r in (raw or [])]

    def wait_and_collect(self) -> List[Tuple[str, str, str]]:
        """描画待ち + 空き収集を統合。ループ1回分のSelenium往復を最小化。"""
        try:
            WebDriverWait(self.driver, self.RENDER_TIMEOUT).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, "span[id^='facility']")
                or d.find_elements(By.XPATH, self.BOUNDARY_XPATH)
            )
        except Exception:
            pass
        return self.collect_available()

    def collect_available_names(self) -> Set[str]:
        return {name for name, _, _ in self.collect_available()}

    def collect_available_with_links(self, target_month: str) -> List[str]:
        lines: List[str] = []
        for name, lgc, fc in self.collect_available():
            url = (
                f"https://yoyaku.harp.lg.jp/sapporo/FacilityAvailability/Index/{lgc}/{fc}"
                f"?ptn=1&d={target_month}"
            )
            lines.append(f"・{name}\n  {url}")
        return lines

    # ---------- ポップアップスキップ ----------

    def skip_popup_if_exists(self) -> bool:
        """
        説明ポップアップ（v-overlay--active）が既に出ていればスキップする。
        ★高速化: 既にDOMに存在するか即チェック（待機なし）。
          出ていなければ 0.5秒だけ待って再チェック → なければ即リターン。
        スキップボタン: <button><span class='v-btn__content'>スキップ</span></button>
        """
        # DOMに v-overlay--active が既にあるか即確認（待機なし）
        overlays = self.driver.find_elements(
            By.XPATH, "//div[contains(@class,'v-overlay--active')]"
        )
        if not overlays:
            # 0.2秒だけ待って再チェック（Vue.jsレンダリング遅延の最低限の考慮）
            time.sleep(0.2)
            overlays = self.driver.find_elements(
                By.XPATH, "//div[contains(@class,'v-overlay--active')]"
            )
        if not overlays:
            return False  # ポップアップなし → 即リターン

        # スキップボタンを即クリック
        try:
            btn = WebDriverWait(self.driver, 2).until(
                EC.element_to_be_clickable(
                    (By.XPATH,
                     "//button[.//span[contains(text(),'スキップ')]]"
                     " | //span[contains(text(),'スキップ')]")
                )
            )
            self.driver.execute_script("arguments[0].click();", btn)
            self.log("[OK] スキップボタンをクリック")
            # オーバーレイが消えるまで最大1秒待つ
            try:
                WebDriverWait(self.driver, 1).until(
                    EC.invisibility_of_element_located(
                        (By.XPATH, "//div[contains(@class,'v-overlay--active')]")
                    )
                )
            except Exception:
                pass
            return True
        except Exception:
            self.log("[Warn] スキップボタンが見つかりません（ポップアップなし）")
            return False

    # ---------- 時間帯選択 ----------

    def click_time_slot(self, monitor_url: str, time_slots: List[str]) -> bool:
        """
        時間帯ボタンを選択する。
        同じ時間帯に「半面A」「半面B」「全面」が並ぶ場合は
        半面A → 半面B → 全面 の優先順でクリックする。
        """
        # 半面/全面の優先順（titleに含まれるキーワード順）
        AREA_PRIORITY = ["半面A", "半面B", "全面"]

        wait = WebDriverWait(self.driver, 3)
        for title in time_slots:
            # まずその時間帯のボタンを全て取得（最大3秒待機）
            try:
                wait.until(
                    EC.presence_of_element_located(
                        (By.XPATH, f"//button[contains(@title,'{title}')]")
                    )
                )
            except Exception:
                continue  # この時間帯のボタン自体が存在しない

            # 時間帯にマッチするボタンを全件取得
            candidates = self.driver.find_elements(
                By.XPATH, f"//button[contains(@title,'{title}')]"
            )
            if not candidates:
                continue

            # 半面A/B/全面 キーワードが title に含まれるボタンを優先順に探す
            clicked = False
            for area in AREA_PRIORITY:
                for btn in candidates:
                    btn_title = btn.get_attribute("title") or ""
                    if area in btn_title:
                        try:
                            self.driver.execute_script("arguments[0].click();", btn)
                            self.log(f"[OK] 時間帯選択: {btn_title[:80]} （{area}優先）")
                            clicked = True
                        except Exception:
                            continue
                        break
                if clicked:
                    return True

            # 半面/全面 キーワードなし → 最初のボタンをそのままクリック
            try:
                self.driver.execute_script("arguments[0].click();", candidates[0])
                btn_title = candidates[0].get_attribute("title") or title
                self.log(f"[OK] 時間帯選択: {btn_title[:80]}")
                return True
            except Exception:
                continue

        self.log("[Info] 希望時間帯に空き無し → 監視復帰")
        self.driver.get(monitor_url)
        return False

    # ---------- 予約処理 ----------

    def reserve_from_current_detail(self, monitor_url: str, school_name: str = "") -> bool:
        try:
            # ---- 確認ボタン（時間帯選択後） ----
            # ★高速化: 3秒タイムアウト
            confirm = WebDriverWait(self.driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'確認')]"))
            )
            self.driver.execute_script("arguments[0].click();", confirm)
            self.log("[OK] 確認をクリック")

            # ---- 予約申込へ ----
            reserve_btn = WebDriverWait(self.driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'予約申込へ')]"))
            )
            self.driver.execute_script("arguments[0].click();", reserve_btn)
            self.log("[OK] 予約申込へをクリック")

            # ---- 内容入力ページのロード完了を待つ ----
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//input[@type='text']")
                    )
                )
            except Exception:
                self.log("[Warn] 内容入力ページのロードタイムアウト → 監視に戻ります")
                self.driver.get(monitor_url)
                return False

            # ---- 内容入力ページ: 利用目的を設定 ----
            # ページ構造（デバッグ確認済み）:
            #   type=text[0] = 利用目的 v-select (id="input-54")
            #   type=text[1] = 利用人数 (id="input-61")
            # v-menu__content 内に限定することでナビメニューとの混同を防ぐ

            purpose_keyword = self.config.get("purpose", "バレーボール")
            self.log(f"[Info] 利用目的を設定します: {purpose_keyword}")

            text_inputs = self.driver.find_elements(By.XPATH, "//input[@type='text']")
            self.log(f"[Info] type=text input数: {len(text_inputs)}")

            # ---- 利用目的: 1番目のtype=text をクリックしてドロップダウンを開く ----
            # ★ここで purpose_keyword が選択肢に無い施設は予約対象外として除外する
            if text_inputs:
                purpose_input = text_inputs[0]
                purpose_missing = False
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", purpose_input)
                    self.driver.execute_script("arguments[0].click();", purpose_input)
                    self.log("[OK] 利用目的ドロップダウンを開きました")
                    time.sleep(0.3)

                    # v-menu__content 内（表示中のドロップダウン）の v-list-item--link だけを対象にする
                    # これによりナビメニューの v-list-item と混同しない
                    menu_xpath = (
                        f"//div[contains(@class,'v-menu__content')]"
                        f"//div[contains(@class,'v-list-item--link') and contains(.,'{purpose_keyword}')]"
                    )
                    try:
                        purpose_item = WebDriverWait(self.driver, 3).until(
                            EC.element_to_be_clickable((By.XPATH, menu_xpath))
                        )
                    except Exception:
                        # 選択肢に無い → この施設では該当種目を予約できないので除外
                        purpose_missing = True

                    if not purpose_missing:
                        self.driver.execute_script("arguments[0].scrollIntoView(true);", purpose_item)
                        self.driver.execute_script("arguments[0].click();", purpose_item)
                        self.log(f"[OK] 利用目的選択: {purpose_item.text!r}")
                except Exception as e:
                    self.log(f"[Warn] 利用目的ドロップダウン選択失敗: {str(e).splitlines()[0]}")

                if purpose_missing:
                    label = school_name or "この施設"
                    self.log(
                        f"[Skip] {label} は「{purpose_keyword}」を選べません → 対象外として次の施設へ"
                    )
                    self.driver.get(monitor_url)
                    return False

            # ---- 利用人数: JavaScriptで確実に2番目のtype=textを特定して入力 ----
            try:
                people_box = self.driver.execute_script("""
                    var inputs = Array.from(document.querySelectorAll('input[type="text"]'));
                    return inputs.length >= 2 ? inputs[1] : (inputs.length ? inputs[0] : null);
                """)
                if people_box:
                    people_box.clear()
                    people_box.send_keys(str(self.config["num_people"]))
                    self.log(f"[OK] 利用人数 {self.config['num_people']} を入力")
                else:
                    self.log("[Warn] 利用人数入力欄が見つかりません")
            except Exception as e:
                self.log(f"[Warn] 利用人数入力失敗: {str(e).splitlines()[0]}")

            # ---- 支払方法へ ----
            pay_btn = WebDriverWait(self.driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, "//span[contains(.,'支払方法へ')]"))
            )
            url_before_pay = self.driver.current_url
            self.driver.execute_script("arguments[0].click();", pay_btn)
            self.log("[OK] 『支払方法へ』クリック")

            # URLが変わったかで遷移成功を判定（最大3秒）
            try:
                WebDriverWait(self.driver, 3).until(
                    lambda d: d.current_url != url_before_pay
                )
                self.log("[OK] 支払方法ページへ遷移")
            except Exception:
                # 遷移しなかった場合のみ再クリック
                try:
                    pay_btn2 = WebDriverWait(self.driver, 2).until(
                        EC.element_to_be_clickable((By.XPATH, "//span[contains(.,'支払方法へ')]"))
                    )
                    self.driver.execute_script("arguments[0].click();", pay_btn2)
                    self.log("[OK] 『支払方法へ』再クリック")
                    time.sleep(0.3)
                except Exception:
                    pass

            # ================================================================
            # ステップ2: 支払方法ページ → 「確認」ボタンをクリック
            # ================================================================
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'支払方法')]"))
            )
            self.log("[OK] 支払方法ページに遷移しました")

            # 支払方法ページの「確認」ボタンをクリック
            step2_confirm = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable(
                    (By.XPATH,
                     "//button[contains(.,'確認')]"
                     " | //span[contains(@class,'v-btn__content') and contains(.,'確認')]"
                     "/parent::button")
                )
            )
            self.driver.execute_script("arguments[0].scrollIntoView(true);", step2_confirm)
            self.driver.execute_script("arguments[0].click();", step2_confirm)
            self.log("[OK] 支払方法ページ「確認」をクリック")

            # ================================================================
            # ステップ3: 確認ページ → チェックボックス → 「申込確定」ボタン
            # ================================================================
            # 確認ページのロード待ち
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//*[contains(text(),'注意事項') or contains(text(),'申込確定') or contains(text(),'確認しました')]")
                )
            )
            self.log("[OK] 申込確認ページに遷移しました")

            # 「注意事項を確認しました」チェックボックスをチェック
            try:
                checkboxes = self.driver.find_elements(By.XPATH, "//input[@type='checkbox']")
                self.log(f"[Info] チェックボックス数: {len(checkboxes)}")
                for cb in checkboxes:
                    if not cb.is_selected():
                        self.driver.execute_script("arguments[0].scrollIntoView(true);", cb)
                        self.driver.execute_script("arguments[0].click();", cb)
                        self.log("[OK] 「注意事項を確認しました」チェック完了")
                        time.sleep(0.2)
            except Exception as e:
                self.log(f"[Warn] チェックボックス操作: {e}")

            # 「申込確定」ボタンをクリック
            final_btn = None
            for xpath in [
                "//button[contains(.,'申込確定')]",
                "//button[contains(.,'申込を確定')]",
                "//span[contains(.,'申込確定')]/parent::button",
                "//button[contains(.,'確定')]",
                "//button[contains(.,'予約確定')]",
                "//button[contains(.,'申込する')]",
            ]:
                try:
                    final_btn = WebDriverWait(self.driver, 3).until(
                        EC.element_to_be_clickable((By.XPATH, xpath))
                    )
                    self.log(f"[OK] 申込確定ボタン発見: {final_btn.text.strip()!r}")
                    break
                except Exception:
                    continue

            if final_btn:
                self.driver.execute_script("arguments[0].scrollIntoView(true);", final_btn)
                self.driver.execute_script("arguments[0].click();", final_btn)
                self.log("[OK] 申込確定をクリック → 予約完了処理中...")
                time.sleep(1)

                # ---- 予約完了確認 ----
                complete_texts = ["予約が完了", "申込が完了", "受付番号", "予約番号", "完了しました", "申込完了"]
                page_text = self.driver.page_source
                found = next((t for t in complete_texts if t in page_text), None)
                if found:
                    self.log(f"[END] 予約完了確認: '{found}' を検出")
                    self.send_discord(
                        f"✅【予約完了】\n"
                        f"施設の予約が完了しました！\n"
                        f"日時: {self.config['target_date']}\n"
                        f"人数: {self.config['num_people']}人\n"
                        f"URL: {self.driver.current_url}"
                    )
                    return True  # ★本当の成功のみ True
                else:
                    self.log("[Warn] 予約完了テキストが見つかりません → 監視に戻ります")
                    self.driver.get(monitor_url)
                    return False  # ★失敗 → 監視ループへ戻る
            else:
                self.log("[Warn] 申込確定ボタンが見つかりません → 監視に戻ります")
                self.driver.get(monitor_url)
                return False  # ★失敗 → 監視ループへ戻る

        except Exception as e:
            self.log(f"[Error] 予約処理エラー: {str(e).splitlines()[0]}")
            self.driver.get(monitor_url)
            return False

    # ---------- 空き状況→予約 ----------

    def click_aki_and_reserve(self, school_name: str, lgc: str, fc: str,
                              monitor_url: str, time_slots: List[str],
                              target_month: str) -> bool:
        """
        施設一覧ページから「空き状況」ボタンを直接クリックして予約する。
        ボタンクリック方式: driver.get() によるフルページ遷移を省略し高速化。
        フォールバック: ボタンが見つからない場合はURL直接遷移。

        ★重要: 空き状況ページは2段階構造
          1. ページ表示 → カレンダーの日付ボタンをクリック
          2. 日付クリック後 → 時間帯ボタンが出現する
        """
        try:
            self.log(f"[Info] 空き状況ページへ遷移 → {school_name}")

            # ★高速化: 施設一覧ページ上の「空き状況」ボタンを直接クリック
            #   <button>...<span class="h-hiddenAccessible">光陽中学校の</span>空き状況...</button>
            aki_btn_xpath = (
                f"//span[contains(@class,'h-hiddenAccessible') and contains(text(),'{school_name}')]"
                f"/ancestor::button"
            )
            navigated_by_btn = False
            try:
                aki_btn = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((By.XPATH, aki_btn_xpath))
                )
                self.driver.execute_script("arguments[0].click();", aki_btn)
                self.log(f"[OK] 「{school_name}」空き状況ボタンをクリック")
                navigated_by_btn = True
            except Exception:
                # フォールバック: URL直接遷移
                avail_url = (
                    f"https://yoyaku.harp.lg.jp/sapporo/FacilityAvailability/Index/{lgc}/{fc}"
                    f"?ptn=1&d={target_month}"
                )
                self.log(f"[Info] ボタン未検出 → URL直接遷移")
                self.driver.get(avail_url)

            # ページ本体（カレンダーボタン）が出るか、ポップアップが出るまで待つ
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda d: (
                        d.find_elements(By.XPATH, "//div[contains(@class,'v-overlay--active')]")
                        or d.find_elements(By.CLASS_NAME, "AvailabilityTable_item")
                    )
                )
            except Exception:
                pass

            # ポップアップスキップ（出ていれば消す）
            self.skip_popup_if_exists()

            # ★STEP1: 対象日付のボタンをクリックして時間帯ボタンを出現させる
            date = datetime.date.fromisoformat(target_month)
            month = date.month
            day = date.day
            date_xpath = (
                f"//button[contains(@title,'{month}月{day}日') and contains(@title,'利用可能')]"
            )
            try:
                date_btn = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, date_xpath))
                )
                self.log(f"[OK] 日付ボタン発見: {date_btn.get_attribute('title')[:60]}")
                self.driver.execute_script("arguments[0].click();", date_btn)
                self.log("[OK] 日付クリック完了")
                # 日付クリック後にもスキップポップアップが出る場合があるので対処
                self.skip_popup_if_exists()
            except Exception as e:
                self.log(f"[Warn] 日付ボタンが見つかりません ({month}月{day}日 利用可能): {e}")
                self.log("[Info] 時間帯ボタンを直接探します（日付クリックなし）")

            # ★STEP2: 時間帯自動選択（日付クリック後に出現したボタン）
            if not self.click_time_slot(monitor_url, time_slots):
                return False

            # ★STEP3: 確認→申込→人数→支払方法
            #   （内容入力ページで利用目的が選べない施設はここで除外される）
            return self.reserve_from_current_detail(monitor_url, school_name)

        except Exception as e:
            self.log(f"[Error] 予約処理エラー ({school_name}): {str(e).splitlines()[0]}")
            self.driver.get(monitor_url)
            return False

    # ---------- セッション生存チェック ----------

    def _is_session_alive(self) -> bool:
        """Chrome セッションが生きているか簡易チェック"""
        try:
            _ = self.driver.current_url
            return True
        except Exception:
            return False

    def _restart_browser(self, target_url: str) -> bool:
        """ブラウザを再起動してログインし直す"""
        self.log("[Info] ブラウザを再起動します...")
        try:
            self.driver.quit()
        except Exception:
            pass
        try:
            self.driver = self.build_driver()
            self.login()
            self.driver.get(target_url)
            self.log("[OK] ブラウザ再起動・再ログイン完了")
            return True
        except Exception as e:
            self.log(f"[Error] ブラウザ再起動失敗: {str(e).splitlines()[0]}")
            return False

    # ---------- メインループ ----------

    def run(self):
        target_month = self.config["target_date"]
        time_slots = get_time_slots(target_month)
        is_weekend = datetime.date.fromisoformat(target_month).weekday() >= 5
        is_hol = is_holiday_jp(datetime.date.fromisoformat(target_month))
        day_type = "土日祝" if (is_weekend or is_hol) else "平日"
        self.log(f"[Info] 監視開始: {target_month}（{day_type}）→ {time_slots[0][:7]} 優先")

        target_url = (
            f"https://yoyaku.harp.lg.jp/sapporo/FacilitySearch/Index/"
            f"?u%5B0%5D=70&ud={target_month}"
        )

        try:
            self.driver = self.build_driver()
            self.login()
            self.driver.get(target_url)
        except Exception as e:
            self.log(f"[Error] 初期化エラー: {e}")
            traceback.print_exc()
            return

        prev: Set[str] = set()           # 前回ループで空きが確認された施設名
        failed_names: Set[str] = set()   # 今回の空き出現中に失敗済みの施設名
        loop_count = 0
        consecutive_errors = 0           # 連続エラー回数
        MAX_CONSECUTIVE_ERRORS = 3       # 連続エラー上限（超えたら停止）

        while not self.stop_event.is_set():
            try:
                # セッション生存チェック
                if not self._is_session_alive():
                    self.log("[Warn] Chromeセッションが切れています")
                    if not self._restart_browser(target_url):
                        consecutive_errors += 1
                        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                            self.log(f"[Error] ブラウザ再起動が{MAX_CONSECUTIVE_ERRORS}回連続失敗 → 監視を停止します")
                            self.stop_event.set()
                            return
                        time.sleep(5)
                        continue
                    consecutive_errors = 0

                self.driver.refresh()
                available = self.wait_and_collect()
                names = {name for name, _, _ in available}

                # ★空きが消えた学校は failed_names から除外する
                # 　「一度空きなしになった = リセット済み」なので次に空きが出たら再挑戦可能
                vanished = failed_names - names  # 空きリストから消えた学校
                if vanished:
                    self.log(f"[Info] 空きが消えたため諦めリストから除外: {sorted(vanished)}")
                    failed_names -= vanished

                # 新規 = 前回未確認 かつ 今回の出現で失敗済みでない
                added_names = sorted(list(names - prev - failed_names))

                loop_count += 1
                self.log(
                    f"#{loop_count} 空き: {len(names)}件 / 未試行新規: {len(added_names)}件"
                    + (f" / スキップ中: {sorted(failed_names)}" if failed_names else "")
                )

                # エラーなく回れたのでリセット
                consecutive_errors = 0

                if added_names:
                    lines = self.collect_available_with_links(target_month)
                    new_lines = [
                        line for line in lines
                        if line.split("\n", 1)[0].lstrip("・").strip() in added_names
                    ]
                    if loop_count > 1:
                        self.send_discord_lines(new_lines)

                    # ★空きあり施設を上から順に試す。失敗した学校は諦めて次へ進む。
                    for name, lgc, fc in available:
                        if self.stop_event.is_set():
                            break
                        if name not in added_names:
                            continue
                        self.log(f"[Try] 予約を試みます → {name}")
                        success = self.click_aki_and_reserve(
                            name, lgc, fc, target_url, time_slots, target_month
                        )
                        if success:
                            self.log("[END] 予約完了")
                            self.stop_event.set()
                            return
                        else:
                            # 失敗 → この"空き出現中"は諦め、次の学校へ
                            # ※ 一度空きが消えて再出現したら failed_names から自動除外される
                            self.log(f"[Info] {name} 予約失敗 → 今回の空き出現は諦め。次の学校へ")
                            failed_names.add(name)
                            # 監視ページに戻って次の施設へ
                            try:
                                self.driver.get(target_url)
                                available = self.wait_and_collect()
                                names = {n for n, _, _ in available}
                                # 空きが消えた学校を failed_names から除外（ここでも即反映）
                                failed_names -= (failed_names - names)
                                added_names = sorted(list(names - prev - failed_names))
                            except Exception as e:
                                self.log(f"[Warn] 監視ページ再取得失敗: {e}")

                    # 全施設を試し終えた → prev を更新して次ループへ
                    if not self.stop_event.is_set():
                        prev = names
                        self.driver.get(target_url)

                else:
                    # 未試行の新規なし → prev 更新して待機
                    prev = names

            except Exception as e:
                err_msg = str(e).splitlines()[0]
                self.log(f"[Error] 監視ループで例外: {err_msg}")

                # セッション切れ系のエラー → ブラウザ再起動
                if "invalid session" in err_msg.lower() or "no such window" in err_msg.lower():
                    if not self._restart_browser(target_url):
                        consecutive_errors += 1
                        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                            self.log(f"[Error] 再起動{MAX_CONSECUTIVE_ERRORS}回連続失敗 → 監視を停止します")
                            self.stop_event.set()
                            return
                    else:
                        consecutive_errors = 0
                else:
                    # その他のエラー → 従来通り監視ページに戻す試行
                    consecutive_errors += 1
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        self.log(f"[Error] 連続エラー{MAX_CONSECUTIVE_ERRORS}回 → ブラウザ再起動を試みます")
                        if not self._restart_browser(target_url):
                            self.log("[Error] ブラウザ再起動も失敗 → 監視を停止します")
                            self.stop_event.set()
                            return
                        consecutive_errors = 0
                    else:
                        try:
                            self.driver.get(target_url)
                        except Exception:
                            pass

            time.sleep(self.config["interval_sec"])

        self.log("[Info] 監視を停止しました")
        try:
            self.driver.quit()
        except Exception:
            pass
