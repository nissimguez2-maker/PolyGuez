<<<<<<< Current (Your changes)
=======
@echo off
REM Start Trading Bot Server im Hintergrund (ohne Fenster)
REM Dieser Server läuft auch weiter, wenn Cursor geschlossen wird

cd /d "%~dp0"

REM Prüfe ob Server bereits läuft
REM Versuche alte uvicorn/python Prozesse zu beenden (sauberer Neustart)
echo Prüfe auf laufende uvicorn Prozesse...
REM Setze UTF-8 Ausgabe für Python und Konsole, um Encoding-Fehler mit Emojis zu vermeiden
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM Suche Prozesse mit webhook_server_fastapi in der Kommandozeile und beende sie (WMIC)
set "TMPFILE=%TEMP%\\uvicorn_pids.txt"
echo DEBUG: vor WMIC
wmic process where "CommandLine like '%%webhook_server_fastapi%%' and CommandLine like '%%uvicorn%%'" get ProcessId /format:value > "%TMPFILE%" 2>nul
echo DEBUG: nach WMIC
for /f "tokens=2 delims==" %%P in (%TMPFILE%) do (
    if not "%%P"=="" (
        echo Beende Prozess: %%P
        taskkill /PID %%P /F >nul 2>&1
    )
)
del /f /q "%TMPFILE%" >nul 2>&1

REM Warte kurz, dann prüfe ob Port 5000 noch belegt ist
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":5000" >nul 2>&1
if %errorlevel% == 0 (
    echo Server läuft bereits auf Port 5000
    echo Zum Stoppen: taskkill /F /FI "WINDOWTITLE eq TradingBotServer*"
    exit /b 0
)

REM Starte Server im Hintergrund (ohne Fenster)
echo Starte Trading Bot Server im Hintergrund...
REM Start server hidden via PowerShell to avoid input-redirection warnings
echo DEBUG: vor Start-Process
powershell -NoProfile -Command "Start-Process -FilePath 'python' -ArgumentList '-m','uvicorn','webhook_server_fastapi:app','--host','0.0.0.0','--port','5000' -WindowStyle Hidden" >nul 2>&1
echo DEBUG: nach Start-Process

REM Warte kurz und prüfe ob Server gestartet ist
timeout /t 2 /nobreak >nul
netstat -ano | findstr ":5000" >nul 2>&1
echo DEBUG: nach netstat
if %errorlevel% == 0 (
    echo ✅ Server erfolgreich gestartet!
    echo Server läuft im Hintergrund und sammelt Trades auch wenn Cursor geschlossen ist.
    echo Zum Prüfen: curl http://127.0.0.1:5000/health
) else (
    echo ❌ Server konnte nicht gestartet werden
    echo Prüfe Logs: logs\app.log
)
>>>>>>> Incoming (Background Agent changes)
