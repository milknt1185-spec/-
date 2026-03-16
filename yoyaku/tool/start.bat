@echo off
chcp 65001 > nul
title 札幌体育館 自動予約ツール

echo ============================================
echo   札幌市体育館 自動予約ツール - Webサーバー版
echo ============================================
echo.

:: Pythonの確認
python --version > nul 2>&1
if errorlevel 1 (
    echo [Error] Python が見つかりません。
    echo         https://www.python.org からインストールしてください。
    pause
    exit /b 1
)

:: 依存パッケージのインストール（初回のみ時間がかかります）
echo [Info] 依存パッケージを確認中...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo [Error] パッケージのインストールに失敗しました。
    pause
    exit /b 1
)

:: PINが未設定なら初回設定を促す
echo.
echo [Info] PINが未設定の場合はアクセス制限なしで起動します。
echo        PINを設定するには: python set_pin.py
echo.

:: サーバー起動
echo [Info] サーバーを起動します...
echo.
echo  ブラウザで http://localhost:5000 を開いてください
echo  スマホからは http://[このPCのIPアドレス]:5000 を開いてください
echo.
echo  ※ このウィンドウを閉じるとサーバーが停止します
echo.

python web_app.py

pause
