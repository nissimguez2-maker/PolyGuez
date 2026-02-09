@echo off
REM Improved auto-start script for Trading Bot Server (silent, robust)
cd /d "%~dp0"

REM Set UTF-8 for console/python
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM Kill all python processes to ensure clean start (best-effort)
echo Stopping existing python processes...
taskkill /F /IM python.exe >nul 2>&1

REM Wait and ensure port 5000 is free (retry)
set RETRIES=6
set /A COUNT=0
:wait_port_free
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":5000" >nul 2>&1
if %errorlevel% == 0 (
    set /A COUNT+=1
    if %COUNT% GEQ %RETRIES% (
        echo Port 5000 offenbar belegt. Abbruch.
        exit /b 1
    )
    goto wait_port_free
)

REM Start server using pythonw (no console) to avoid input-redirection warnings
echo Starting Trading Bot Server...
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath 'pythonw' -ArgumentList '-m','uvicorn','webhook_server_fastapi:app','--host','0.0.0.0','--port','5000' -WindowStyle Hidden" >nul 2>&1

REM Wait for server to listen (max 20s)
set RETRIES2=20
set /A COUNT2=0
:wait_port_listen
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":5000" >nul 2>&1
if %errorlevel% == 0 (
    echo Server erfolgreich gestartet und lauscht auf Port 5000.
    exit /b 0
)
set /A COUNT2+=1
if %COUNT2% LSS %RETRIES2% goto wait_port_listen

echo Server konnte nicht gestartet. Logs prüfen: logs\app.log
exit /b 2

