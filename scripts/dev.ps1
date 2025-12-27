$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$psExe = if (Get-Command pwsh -ErrorAction SilentlyContinue) { "pwsh" } else { "powershell" }

function Start-Terminal([string]$title, [string]$command) {
  $cmd = "$Host.UI.RawUI.WindowTitle='$title'; Set-Location '$repoRoot'; $command"
  Start-Process $psExe -ArgumentList @("-NoExit","-Command",$cmd) -WorkingDirectory $repoRoot | Out-Null
}

Write-Host ""
Write-Host "Starting dev terminals..." -ForegroundColor Cyan

Start-Terminal "API :3001" "pnpm dev:api"
Start-Terminal "WEB :3000" "pnpm dev:web"

Write-Host ""
Write-Host "Started API and WEB in separate terminals." -ForegroundColor Green
Write-Host "Health checks:" -ForegroundColor Gray
Write-Host "  Invoke-WebRequest http://127.0.0.1:3001/health -UseBasicParsing" -ForegroundColor Gray
Write-Host "  Invoke-WebRequest http://127.0.0.1:3000/ -UseBasicParsing" -ForegroundColor Gray
Write-Host ""
