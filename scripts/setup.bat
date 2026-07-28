@echo off
REM Alap-Alap Setup Script for Windows

echo 🦅 Alap-Alap Setup
echo ==================
echo.

REM Check Python version
echo Checking Python version...
python --version
echo.

REM Create virtual environment
echo Creating virtual environment...
python -m venv venv

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo.
echo Installing dependencies...
pip install --upgrade pip
pip install -e ".[dev]"

REM Install Camoufox browser
echo.
echo Installing Camoufox browser...
camoufox fetch

echo.
echo ✅ Setup complete!
echo.
echo To activate the virtual environment:
echo   venv\Scripts\activate.bat
echo.
echo To start the API server:
echo   python -m alap_alap.api.server
