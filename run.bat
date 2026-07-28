@echo off

REM Check if .venv exists
if not exist ".venv" (
    echo Virtual environment not found! Running setup first...
    call setup.bat
)

REM Activate and run
call .venv\Scripts\activate.bat
python main.py %*
