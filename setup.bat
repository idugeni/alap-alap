@echo off
setlocal

echo.
echo ========================================
echo   Alap-Alap Setup
echo ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Please install Python 3.8+
    pause
    exit /b 1
)

REM Check if .venv exists
if not exist ".venv" (
    echo [1/4] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo       Done!
) else (
    echo [1/4] Virtual environment already exists
)

REM Activate venv
echo [2/4] Activating virtual environment...
call .venv\Scripts\activate.bat

REM Install dependencies
echo [3/4] Installing dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)
echo       Done!

REM Install browsers
echo [4/4] Installing browsers...
camoufox fetch --quiet 2>nul
playwright install chromium --quiet 2>nul
echo       Done!

echo.
echo ========================================
echo   Setup Complete!
echo ========================================
echo.
echo   Run: run.bat
echo   Or:  .venv\Scripts\python.exe main.py
echo.

pause
