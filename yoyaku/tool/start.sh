#!/bin/bash
# 札幌市体育館 自動予約ツール - Webサーバー版起動スクリプト（Mac/Linux用）

# スクリプトのあるディレクトリに移動
cd "$(dirname "$0")"

echo "============================================"
echo "  札幌市体育館 自動予約ツール - Webサーバー版"
echo "============================================"
echo ""

# Pythonの確認
if ! command -v python3 &>/dev/null; then
    echo "[Error] python3 が見つかりません。インストールしてください。"
    exit 1
fi

# 依存パッケージのインストール
echo "[Info] 依存パッケージを確認中..."
pip3 install -r requirements.txt -q --ignore-installed --break-system-packages 2>/dev/null \
  || pip3 install -r requirements.txt -q --ignore-installed 2>/dev/null \
  || pip3 install -r requirements.txt -q
if ! python3 -c "import flask, selenium, jpholiday" 2>/dev/null; then
    echo "[Error] 必要なパッケージが不足しています。"
    exit 1
fi

echo ""
echo "[Info] PINが未設定の場合はアクセス制限なしで起動します。"
echo "       PINを設定するには: python3 set_pin.py"
echo ""

# ローカルIPを表示
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
echo "[Info] サーバーを起動します..."
echo ""
echo "  ブラウザで http://localhost:5000 を開いてください"
if [ -n "$LOCAL_IP" ]; then
    echo "  スマホからは http://${LOCAL_IP}:5000 を開いてください"
fi
echo ""
echo "  ※ Ctrl+C でサーバーを停止します"
echo ""

python3 web_app.py
