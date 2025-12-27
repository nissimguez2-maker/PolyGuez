# Quick Port Fix Script for Windows PowerShell
# Fixes ports 3000/3001 and provides verification commands

Write-Host "=== Port Troubleshooting Script ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: List current listeners
Write-Host "Step 1: Checking ports 3000/3001..." -ForegroundColor Yellow
$listeners = Get-NetTCPConnection -LocalPort 3000,3001 -ErrorAction SilentlyContinue
if ($listeners) {
    $listeners | Select-Object LocalPort, State, OwningProcess | ForEach-Object { 
        $proc = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
        [PSCustomObject]@{
            Port = $_.LocalPort
            State = $_.State
            PID = $_.OwningProcess
            ProcessName = if ($proc) { $proc.Name } else { "Unknown" }
        }
    } | Format-Table -AutoSize
} else {
    Write-Host "✅ Ports 3000 and 3001 are free" -ForegroundColor Green
}

Write-Host ""

# Step 2: Kill listeners
Write-Host "Step 2: Killing processes on ports 3000/3001..." -ForegroundColor Yellow
$killed = $false

$conn3000 = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue
if ($conn3000) {
    $pid = $conn3000.OwningProcess
    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
    Write-Host "  Killing PID $pid on port 3000 ($($proc.Name))" -ForegroundColor Gray
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    $killed = $true
    Start-Sleep -Milliseconds 500
}

$conn3001 = Get-NetTCPConnection -LocalPort 3001 -ErrorAction SilentlyContinue
if ($conn3001) {
    $pid = $conn3001.OwningProcess
    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
    Write-Host "  Killing PID $pid on port 3001 ($($proc.Name))" -ForegroundColor Gray
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    $killed = $true
    Start-Sleep -Milliseconds 500
}

if ($killed) {
    Write-Host "✅ Processes killed. Waiting 1 second for ports to release..." -ForegroundColor Green
    Start-Sleep -Seconds 1
} else {
    Write-Host "✅ No processes to kill" -ForegroundColor Green
}

# Verify ports are free
Write-Host ""
Write-Host "Step 3: Verifying ports are free..." -ForegroundColor Yellow
$remaining = Get-NetTCPConnection -LocalPort 3000,3001 -ErrorAction SilentlyContinue
if ($remaining) {
    Write-Host "⚠️  Warning: Ports still in use:" -ForegroundColor Red
    $remaining | Select-Object LocalPort, State, OwningProcess | Format-Table -AutoSize
    Write-Host "   Try running this script again, or manually kill the processes above" -ForegroundColor Yellow
} else {
    Write-Host "✅ Ports 3000 and 3001 are now free" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Next Steps ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Terminal 1 - Start API:" -ForegroundColor Yellow
Write-Host "  cd apps/api" -ForegroundColor White
Write-Host '  $env:DEV_FORCE_TRADES="true"' -ForegroundColor White
Write-Host '  $env:RUNNER_ENABLED="true"' -ForegroundColor White
Write-Host "  pnpm dev" -ForegroundColor White
Write-Host ""
Write-Host "Terminal 2 - Start WEB (after API is running):" -ForegroundColor Yellow
Write-Host "  cd apps/web" -ForegroundColor White
Write-Host "  pnpm dev" -ForegroundColor White
Write-Host ""
Write-Host "Verification Commands (run after both are started):" -ForegroundColor Yellow
Write-Host '  Invoke-WebRequest -Uri "http://localhost:3001/health"' -ForegroundColor White
Write-Host '  Invoke-RestMethod -Uri "http://localhost:3001/agents"' -ForegroundColor White
Write-Host '  Invoke-WebRequest -Uri "http://localhost:3000/"' -ForegroundColor White
Write-Host ""

