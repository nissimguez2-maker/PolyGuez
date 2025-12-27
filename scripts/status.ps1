# Status Script - Shows which processes are listening on ports 3000/3001
# Usage: .\scripts\status.ps1

Write-Host "=== Dev Environment Status ===" -ForegroundColor Cyan
Write-Host ""

$ports = @(3000, 3001)
$found = $false

foreach ($port in $ports) {
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    
    if ($listeners) {
        $found = $true
        $listeners | ForEach-Object {
            $pid = $_.OwningProcess
            $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
            
            Write-Host "Port ${port}:" -ForegroundColor Yellow
            Write-Host "  State:    $($_.State)" -ForegroundColor Gray
            Write-Host "  PID:      $pid" -ForegroundColor Gray
            Write-Host "  Process:  $(if ($proc) { $proc.Name } else { 'Unknown' })" -ForegroundColor Gray
            if ($proc) {
                Write-Host "  Path:     $($proc.Path)" -ForegroundColor Gray
            }
            Write-Host ""
        }
    } else {
        Write-Host "Port ${port}:" -ForegroundColor Yellow
        Write-Host "  Status:   FREE (no listeners)" -ForegroundColor Green
        Write-Host ""
    }
}

if (-not $found) {
    Write-Host "✅ Both ports 3000 and 3001 are free" -ForegroundColor Green
} else {
    Write-Host "💡 To kill processes: pnpm --filter @polymarket/api kill:3001" -ForegroundColor Yellow
    Write-Host "💡 To kill processes: pnpm --filter @polymarket/web kill:3000" -ForegroundColor Yellow
}

Write-Host ""

