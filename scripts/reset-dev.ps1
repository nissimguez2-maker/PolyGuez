param(
  [int[]]$Ports = @(3000,3001)
)

Write-Host ""
Write-Host "Resetting dev environment..." -ForegroundColor Cyan

# Stop Node processes (covers Vite/Express/etc.)
Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 300

function Describe-Conn($c) {
  $p = $null
  try { $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue } catch {}
  [PSCustomObject]@{
    Port    = $c.LocalPort
    State   = $c.State
    PID     = $c.OwningProcess
    Process = if ($p) { $p.ProcessName } else { "" }
    Local   = "$($c.LocalAddress):$($c.LocalPort)"
  }
}

$conns = foreach ($port in $Ports) {
  Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
}

$listening = $conns | Where-Object { $_.State -eq 'Listen' }
$timeWait  = $conns | Where-Object { $_.State -eq 'TimeWait' }

Write-Host ""
if ($listening) {
  Write-Host "Ports in LISTEN (potential conflicts):" -ForegroundColor Yellow
  $listening | ForEach-Object { Describe-Conn $_ } | Format-Table -AutoSize
} else {
  Write-Host "No LISTEN ports found for: $($Ports -join ', ')" -ForegroundColor Green
}

Write-Host ""
if ($timeWait) {
  Write-Host "Ports in TIME_WAIT (harmless, will clear automatically):" -ForegroundColor DarkGray
  $timeWait | Select-Object LocalPort, State | Sort-Object LocalPort | Format-Table -AutoSize
}

Write-Host ""
Write-Host "Tip: If something is still stuck, run:" -ForegroundColor Gray
Write-Host "  Get-NetTCPConnection -LocalPort 3000,3001 -State Listen | Format-Table -AutoSize" -ForegroundColor Gray
Write-Host ""
exit 0
