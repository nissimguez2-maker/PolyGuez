<<<<<<< Current (Your changes)
=======
@echo off
REM Auto-start script for Trading Bot Server
REM This script starts the server and keeps it running

cd /d "%~dp0"

echo ========================================
echo Starting Trading Bot Server...
echo ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH
    echo Please install Python or add it to PATH
    pause
    exit /b 1
)

REM Start server with uvicorn (ohne --reload für Produktion)
REM --reload nur für Entwicklung, entfernen für 24/7 Betrieb
REM Ensure UTF-8 output for Python to avoid emoji encoding errors
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONPATH=%~dp0

python -m uvicorn webhook_server_fastapi:app --host 0.0.0.0 --port 5000 --app-dir "%~dp0"

REM If server exits, pause to see error message
if errorlevel 1 (
    echo.
    echo Server exited with error!
    pause
)
>>>>>>> Incoming (Background Agent changes)
