@echo off
cd /d "%~dp0"
echo ========================================================
echo Starting Mikasa Music Bot on Local PC
echo ========================================================
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    .venv\Scripts\pip install -r requirements-local.txt
)

.venv\Scripts\python -m bobby
pause
