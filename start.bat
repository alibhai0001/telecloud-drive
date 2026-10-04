@echo off
title Telegram Unlimited Cloud Storage Drive
color 0b

echo =======================================================
echo     TELEGRAM UNLIMITED CLOUD STORAGE DRIVE
echo =======================================================
echo.

:: Check python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ from python.org
    pause
    exit /b
)

:: Install dependencies if needed
echo [1/3] Checking requirements...
pip install -r requirements.txt --quiet

:: Start browser after brief delay
echo [2/3] Starting Web UI at http://127.0.0.1:8000 ...
start "" "http://127.0.0.1:8000"

:: Start FastAPI server
echo [3/3] Launching server...
echo.
echo =======================================================
echo   Server is LIVE at: http://127.0.0.1:8000
echo   Press Ctrl+C in this window to stop the server.
echo =======================================================
echo.
python -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload

pause
