# Auto-start script for Trading Bot Server (PowerShell)
# This script starts the server and keeps it running

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptPath

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Starting Trading Bot Server..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Ensure logs directory exists (for ngrok output)
$logsDir = Join-Path $scriptPath "logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

# Check if ngrok is available and start it if needed
$ngrokOutLog = Join-Path $logsDir "ngrok.out.log"
$ngrokErrLog = Join-Path $logsDir "ngrok.err.log"
try {
    $null = ngrok version 2>&1
    $ngrokRunning = Get-Process ngrok -ErrorAction SilentlyContinue
    if (-not $ngrokRunning) {
        Write-Host "Starting ngrok tunnel..." -ForegroundColor Yellow
        Start-Process -FilePath "ngrok" `
            -ArgumentList @("http", "5000", "--log", "stdout") `
            -RedirectStandardOutput $ngrokOutLog `
            -RedirectStandardError $ngrokErrLog `
            -WindowStyle Hidden
        Start-Sleep -Seconds 2
    } else {
        Write-Host "ngrok already running." -ForegroundColor Green
    }
    # Try to fetch public URL from ngrok API
    try {
        $tunnels = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 2
        $publicUrl = $tunnels.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1 -ExpandProperty public_url
        if (-not $publicUrl) {
            $publicUrl = $tunnels.tunnels | Select-Object -First 1 -ExpandProperty public_url
        }
        if ($publicUrl) {
            Write-Host "ngrok public URL: $publicUrl" -ForegroundColor Cyan
        } else {
            Write-Host "ngrok running, but no public URL found yet." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "ngrok running, but API not reachable yet (http://127.0.0.1:4040)." -ForegroundColor Yellow
    }
} catch {
    Write-Host "WARNING: ngrok not found in PATH. Webhooks may not reach the server." -ForegroundColor Yellow
}

# Check if Python is available
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Python: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Python not found in PATH" -ForegroundColor Red
    Write-Host "Please install Python or add it to PATH" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Start server with uvicorn
Write-Host "Starting uvicorn server..." -ForegroundColor Yellow
Write-Host "Server will be available at: http://localhost:5000" -ForegroundColor Gray
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Gray
Write-Host ""

# Ensure UTF-8 for Python and console to avoid encoding errors with emojis
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
# Ensure project root is on PYTHONPATH for "src.*" imports
$env:PYTHONPATH = $scriptPath
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

python -m uvicorn webhook_server_fastapi:app --host 0.0.0.0 --port 5000 --app-dir "$scriptPath"

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Server exited with error code: $LASTEXITCODE" -ForegroundColor Red
    Read-Host "Press Enter to exit"
}
