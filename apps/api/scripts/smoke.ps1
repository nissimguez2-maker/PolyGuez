# Smoke test script for API endpoints
# Verifies that API is responding on all critical endpoints

$ErrorActionPreference = "Stop"
$baseUrl = "http://localhost:3001"
$port = 3001
$failed = $false

Write-Host "`n=== API Smoke Test ===" -ForegroundColor Cyan
Write-Host "Testing API on $baseUrl`n" -ForegroundColor Cyan

# Test 1: Check if port 3001 is open
Write-Host "[1/4] Checking port $port..." -ForegroundColor Yellow
try {
    $connection = Test-NetConnection -ComputerName localhost -Port $port -WarningAction SilentlyContinue -InformationLevel Quiet
    if ($connection) {
        Write-Host "✅ PASS: Port $port is open" -ForegroundColor Green
    } else {
        Write-Host "❌ FAIL: Port $port is not accessible" -ForegroundColor Red
        $failed = $true
    }
} catch {
    Write-Host "❌ FAIL: Port $port is not accessible - $_" -ForegroundColor Red
    $failed = $true
}

# Test 2: GET /health
Write-Host "`n[2/4] Testing GET /health..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$baseUrl/health" -Method GET -UseBasicParsing -TimeoutSec 5
    if ($response.StatusCode -eq 200) {
        $json = $response.Content | ConvertFrom-Json
        $preview = ($response.Content | ConvertFrom-Json | ConvertTo-Json -Compress -Depth 2)
        Write-Host "✅ PASS: /health returned 200" -ForegroundColor Green
        Write-Host "   Preview: $preview" -ForegroundColor Gray
    } else {
        Write-Host "❌ FAIL: /health returned status $($response.StatusCode)" -ForegroundColor Red
        $failed = $true
    }
} catch {
    Write-Host "❌ FAIL: /health endpoint error - $_" -ForegroundColor Red
    $failed = $true
}

# Test 3: GET /agents
Write-Host "`n[3/4] Testing GET /agents..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$baseUrl/agents" -Method GET -UseBasicParsing -TimeoutSec 5
    if ($response.StatusCode -eq 200) {
        $json = $response.Content | ConvertFrom-Json
        $preview = ($response.Content | ConvertFrom-Json | ConvertTo-Json -Compress -Depth 2)
        $agentCount = $json.agents.Count
        Write-Host "✅ PASS: /agents returned 200 ($agentCount agents)" -ForegroundColor Green
        Write-Host "   Preview: $preview" -ForegroundColor Gray
    } else {
        Write-Host "❌ FAIL: /agents returned status $($response.StatusCode)" -ForegroundColor Red
        $failed = $true
    }
} catch {
    Write-Host "❌ FAIL: /agents endpoint error - $_" -ForegroundColor Red
    $failed = $true
}

# Test 4: GET /replay?agentId=agent-1
Write-Host "`n[4/4] Testing GET /replay?agentId=agent-1..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$baseUrl/replay?agentId=agent-1" -Method GET -UseBasicParsing -TimeoutSec 5
    if ($response.StatusCode -eq 200) {
        $json = $response.Content | ConvertFrom-Json
        $preview = ($response.Content | ConvertFrom-Json | ConvertTo-Json -Compress -Depth 2)
        $equityCount = $json.equity.Count
        $tradesCount = $json.trades.Count
        $decisionsCount = $json.decisions.Count
        Write-Host "✅ PASS: /replay returned 200 (equity: $equityCount, trades: $tradesCount, decisions: $decisionsCount)" -ForegroundColor Green
        Write-Host "   Preview: $preview" -ForegroundColor Gray
    } else {
        Write-Host "❌ FAIL: /replay returned status $($response.StatusCode)" -ForegroundColor Red
        $failed = $true
    }
} catch {
    Write-Host "❌ FAIL: /replay endpoint error - $_" -ForegroundColor Red
    $failed = $true
}

# Summary
Write-Host "`n=== Summary ===" -ForegroundColor Cyan
if ($failed) {
    Write-Host "❌ SMOKE TEST FAILED - One or more endpoints are not responding correctly" -ForegroundColor Red
    exit 1
} else {
    Write-Host "✅ SMOKE TEST PASSED - All endpoints are responding correctly" -ForegroundColor Green
    exit 0
}

