# Chat script (generalized)
# Usage: pnpm -C apps/api chat "agent-1" "Your message here"
# Usage: pnpm -C apps/api chat "agent-2" "Hva er status?"
# Or: $env:AGENT_ID="agent-2"; $env:MESSAGE="Your message"; pnpm -C apps/api chat

param(
    [string]$AgentId = $env:AGENT_ID,
    [string]$Message = $env:MESSAGE
)

# If first arg looks like agentId (starts with "agent-"), use it
if ($args.Count -gt 0 -and $args[0] -match '^agent-\d+$') {
    $AgentId = $args[0]
    if ($args.Count -gt 1) {
        $Message = $args[1..($args.Count-1)] -join ' '
    }
} elseif ($args.Count -gt 0 -and -not $Message) {
    # If no agentId pattern and no message, treat first arg as message
    $Message = $args -join ' '
}

# Default agentId if not provided
if (-not $AgentId) {
    $AgentId = 'agent-1'
}

if (-not $Message) {
    Write-Host "Usage: pnpm -C apps/api chat `"agent-1`" `"Your message here`"" -ForegroundColor Red
    Write-Host "Usage: pnpm -C apps/api chat `"agent-2`" `"Hva er status?`"" -ForegroundColor Yellow
    Write-Host "Or: `$env:AGENT_ID=`"agent-1`"; `$env:MESSAGE=`"Your message`"; pnpm -C apps/api chat" -ForegroundColor Yellow
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
    agentId = $AgentId
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
