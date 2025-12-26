# Chat script for agent-1
# Usage: pnpm -C apps/api chat:agent1 "Your message here"
# Or: $env:MESSAGE="Your message"; pnpm -C apps/api chat:agent1

param(
    [string]$Message = $env:MESSAGE
)

if (-not $Message) {
    Write-Host "Usage: pnpm -C apps/api chat:agent1 `"Your message here`"" -ForegroundColor Red
    Write-Host "Or: `$env:MESSAGE=`"Your message`"; pnpm -C apps/api chat:agent1" -ForegroundColor Yellow
    exit 1
}

# Check API health first
try {
    $healthResponse = Invoke-RestMethod -Uri 'http://localhost:3001/health' -Method Get -ErrorAction Stop
} catch {
    Write-Host "API is not running (start with .\scripts\dev.ps1)" -ForegroundColor Red
    exit 1
}

$body = @{
    agentId = 'agent-1'
    message = $Message
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri 'http://localhost:3001/chat' -Method Post -Body $body -ContentType 'application/json' -ErrorAction Stop
    
    if (-not $response.success) {
        Write-Host "Chat failed:" -ForegroundColor Red
        Write-Host "  errorCode: $($response.errorCode)" -ForegroundColor Yellow
        Write-Host "  error: $($response.error)" -ForegroundColor Yellow
        exit 1
    }
    
    $response | ConvertTo-Json -Depth 20
} catch {
    $statusCode = $null
    if ($_.Exception.Response) {
        $statusCode = $_.Exception.Response.StatusCode.value__
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $responseBody = $reader.ReadToEnd()
        try {
            $errorResponse = $responseBody | ConvertFrom-Json
            if ($errorResponse.success -eq $false) {
                Write-Host "Chat failed:" -ForegroundColor Red
                Write-Host "  errorCode: $($errorResponse.errorCode)" -ForegroundColor Yellow
                Write-Host "  error: $($errorResponse.error)" -ForegroundColor Yellow
                if ($statusCode) {
                    Write-Host "  httpStatus: $statusCode" -ForegroundColor Yellow
                }
                exit 1
            }
        } catch {
            # Not JSON, show raw response
        }
        Write-Host "Error: $_" -ForegroundColor Red
        Write-Host "Response: $responseBody" -ForegroundColor Yellow
    } else {
        Write-Host "Error: $_" -ForegroundColor Red
    }
    exit 1
}
