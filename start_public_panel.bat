@echo off
title TeleCloud Drive & Bot - Live Public Panel
color 0a

echo =======================================================
echo     🚀 TELECLOUD DRIVE, BOT & WEB HOSTING PANEL
echo =======================================================
echo.

:: Check python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    pause
    exit /b
)

echo [1/2] Checking requirements...
pip install -r requirements.txt --quiet

echo [2/2] Starting Server with Live Public Tunnel...
echo.
python start_public_panel.py

pause
