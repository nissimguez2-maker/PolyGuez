# Port Troubleshooting Runbook (Windows PowerShell)

## Problem: Ports 3000/3001 not reachable after adding strictPort

This runbook helps diagnose and fix port binding issues.

---

## Step 1: List Listeners on Ports 3000/3001

**Command:**
```powershell
Get-NetTCPConnection -LocalPort 3000,3001 -ErrorAction SilentlyContinue | Select-Object LocalPort, State, OwningProcess | ForEach-Object { 
    $proc = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    [PSCustomObject]@{
        Port = $_.LocalPort
        State = $_.State
        PID = $_.OwningProcess
        ProcessName = $proc.Name
        ProcessPath = $proc.Path
    }
} | Format-Table -AutoSize
```

**Expected output:**
- If ports are free: No output or empty table
- If ports are in use: Table showing PID, process name, and path

**Alternative (simpler):**
```powershell
# Port 3000
Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue | Select-Object LocalPort, State, OwningProcess

# Port 3001
Get-NetTCPConnection -LocalPort 3001 -ErrorAction SilentlyContinue | Select-Object LocalPort, State, OwningProcess
```

---

## Step 2: Kill Listeners Safely

**Command (kills processes on both ports):**
```powershell
# Kill port 3000
$conn3000 = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue
if ($conn3000) {
    $pid = $conn3000.OwningProcess
    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
    Write-Host "Killing process on port 3000: PID=$pid, Name=$($proc.Name)"
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

# Kill port 3001
$conn3001 = Get-NetTCPConnection -LocalPort 3001 -ErrorAction SilentlyContinue
if ($conn3001) {
    $pid = $conn3001.OwningProcess
    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
    Write-Host "Killing process on port 3001: PID=$pid, Name=$($proc.Name)"
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

Write-Host "Port cleanup complete. Verifying ports are free..."
Get-NetTCPConnection -LocalPort 3000,3001 -ErrorAction SilentlyContinue | Select-Object LocalPort, State, OwningProcess
```

**Expected output:**
- Messages showing which processes were killed
- Final verification should show no listeners (or empty output)

---

## Step 3: Start API on Port 3001

**Command (run in Terminal 1):**
```powershell
cd apps/api
$env:DEV_FORCE_TRADES="true"
$env:RUNNER_ENABLED="true"
pnpm dev
```

**Expected output:**
```
[seedAgents] 🔧 DEV_FORCE_TRADES enabled - agent-1 configured for forced trades
[seedAgents] Seeded 3 agents: agent-1, agent-2, agent-3
[Server] ✅ Runner enabled - scheduler started
[Scheduler] Starting with interval 60s
API server running on http://localhost:3001
Scheduler started with 60s interval
```

**Wait for:** "API server running on http://localhost:3001"

**If it fails:**
- Check for EADDRINUSE errors
- Verify port 3001 is actually free (run Step 1 again)
- Check if `kill:3001` script ran successfully

---

## Step 4: Start WEB on Port 3000

**Command (run in Terminal 2, AFTER API is running):**
```powershell
cd apps/web
pnpm dev
```

**Expected output:**
```
  VITE v5.0.11  ready in XXX ms

  ➜  Local:   http://localhost:3000/
  ➜  Network: use --host to expose
  ➜  press h to show help
```

**If it fails with strictPort error:**
- Error: "Port 3000 is in use, exiting."
- Solution: Run Step 2 again, then retry

**If it starts but shows wrong port:**
- Check `vite.config.ts` - should have `port: 3000` in server config
- Command line `--port 3000 --strictPort` should override config
- If still wrong, remove port from vite.config.ts and rely on CLI flags only

---

## Step 5: Verify Services

**Test API Health (should return 200 OK):**
```powershell
try {
    $response = Invoke-WebRequest -Uri "http://localhost:3001/health" -Method Get -UseBasicParsing
    Write-Host "✅ API Health: $($response.StatusCode) - $($response.Content)"
} catch {
    Write-Host "❌ API Health failed: $($_.Exception.Message)"
}
```

**Test API Agents (should return JSON array):**
```powershell
try {
    $response = Invoke-RestMethod -Uri "http://localhost:3001/agents" -Method Get
    Write-Host "✅ API Agents: Found $($response.agents.Count) agents"
    $response | ConvertTo-Json -Depth 2
} catch {
    Write-Host "❌ API Agents failed: $($_.Exception.Message)"
}
```

**Test Web Root (should return HTML):**
```powershell
try {
    $response = Invoke-WebRequest -Uri "http://localhost:3000/" -Method Get -UseBasicParsing
    Write-Host "✅ Web Root: $($response.StatusCode)"
    if ($response.Content -match "<!DOCTYPE html>") {
        Write-Host "✅ HTML content detected"
    } else {
        Write-Host "⚠️  Response doesn't look like HTML"
    }
} catch {
    Write-Host "❌ Web Root failed: $($_.Exception.Message)"
}
```

**Alternative using curl (if available):**
```powershell
# Health
curl http://localhost:3001/health

# Agents
curl http://localhost:3001/agents

# Web root
curl http://localhost:3000/
```

---

## Complete Runbook Script (All-in-One)

**Save as `fix-ports.ps1` and run:**
```powershell
# Step 1: List current listeners
Write-Host "=== Step 1: Checking ports 3000/3001 ===" -ForegroundColor Cyan
Get-NetTCPConnection -LocalPort 3000,3001 -ErrorAction SilentlyContinue | Select-Object LocalPort, State, OwningProcess | ForEach-Object { 
    $proc = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    [PSCustomObject]@{
        Port = $_.LocalPort
        State = $_.State
        PID = $_.OwningProcess
        ProcessName = $proc.Name
    }
} | Format-Table -AutoSize

# Step 2: Kill listeners
Write-Host "`n=== Step 2: Killing processes on ports 3000/3001 ===" -ForegroundColor Cyan
$conn3000 = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue
if ($conn3000) {
    $pid = $conn3000.OwningProcess
    Write-Host "Killing PID $pid on port 3000"
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

$conn3001 = Get-NetTCPConnection -LocalPort 3001 -ErrorAction SilentlyContinue
if ($conn3001) {
    $pid = $conn3001.OwningProcess
    Write-Host "Killing PID $pid on port 3001"
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

Write-Host "✅ Port cleanup complete`n" -ForegroundColor Green

# Step 3: Start API
Write-Host "=== Step 3: Starting API on port 3001 ===" -ForegroundColor Cyan
Write-Host "Run this in a separate terminal:" -ForegroundColor Yellow
Write-Host "cd apps/api" -ForegroundColor White
Write-Host '$env:DEV_FORCE_TRADES="true"' -ForegroundColor White
Write-Host '$env:RUNNER_ENABLED="true"' -ForegroundColor White
Write-Host "pnpm dev`n" -ForegroundColor White

# Step 4: Start WEB
Write-Host "=== Step 4: Starting WEB on port 3000 ===" -ForegroundColor Cyan
Write-Host "After API is running, run this in another terminal:" -ForegroundColor Yellow
Write-Host "cd apps/web" -ForegroundColor White
Write-Host "pnpm dev`n" -ForegroundColor White

# Step 5: Verification commands
Write-Host "=== Step 5: Verification Commands ===" -ForegroundColor Cyan
Write-Host "After both services are running, test with:" -ForegroundColor Yellow
Write-Host 'Invoke-WebRequest -Uri "http://localhost:3001/health"' -ForegroundColor White
Write-Host 'Invoke-RestMethod -Uri "http://localhost:3001/agents"' -ForegroundColor White
Write-Host 'Invoke-WebRequest -Uri "http://localhost:3000/"' -ForegroundColor White
```

---

## Common Issues & Solutions

### Issue 1: "Port 3000 is in use" (strictPort error)
**Cause:** Port not fully released or another process grabbed it
**Solution:**
```powershell
# Kill more aggressively
Get-Process | Where-Object {$_.Path -like "*node*" -or $_.Path -like "*vite*"} | Stop-Process -Force
Start-Sleep -Seconds 2
# Then retry Step 2
```

### Issue 2: API starts but returns 404 on /health
**Cause:** Route not registered or server not fully started
**Solution:**
- Wait 2-3 seconds after "API server running" message
- Check API console for route registration logs
- Verify `apps/api/src/index.ts` has health route

### Issue 3: Web shows unstyled HTML
**Cause:** Tailwind CSS not processing or Vite not serving CSS
**Solution:**
- Check browser console for 404 errors on CSS files
- Verify `apps/web/src/index.css` is imported in `main.tsx`
- Check Vite dev server console for PostCSS errors

### Issue 4: Ports show as LISTENING but services don't respond
**Cause:** Firewall or process in TIME_WAIT state
**Solution:**
```powershell
# Check if ports are actually listening (not TIME_WAIT)
Get-NetTCPConnection -LocalPort 3000,3001 | Where-Object {$_.State -eq "Listen"}
# If empty, ports are in TIME_WAIT - wait 30 seconds or restart services
```

---

## Logs to Collect if Still Failing

### API Logs:
1. **Terminal output from `pnpm dev`** - Look for:
   - "API server running on http://localhost:3001"
   - Any EADDRINUSE errors
   - Route registration messages
   - Scheduler start messages

2. **Check API source:**
   - `apps/api/src/index.ts` - verify PORT and app.listen()
   - `apps/api/src/api/routes.ts` - verify /health route exists

### Web Logs:
1. **Terminal output from `pnpm dev`** - Look for:
   - "Local: http://localhost:3000/"
   - Any port binding errors
   - Vite compilation errors
   - PostCSS/Tailwind warnings

2. **Browser console (F12):**
   - Network tab: Check for failed requests
   - Console tab: Check for JavaScript errors
   - Check if CSS files are loading (200 status)

3. **Check Web source:**
   - `apps/web/vite.config.ts` - verify server.port and proxy config
   - `apps/web/src/main.tsx` - verify index.css import
   - `apps/web/src/index.css` - verify @tailwind directives

### System Logs:
```powershell
# Check Windows Event Viewer for port binding issues
Get-EventLog -LogName System -Newest 50 | Where-Object {$_.Message -like "*3000*" -or $_.Message -like "*3001*"}

# Check firewall rules
Get-NetFirewallRule | Where-Object {$_.DisplayName -like "*3000*" -or $_.DisplayName -like "*3001*"}
```

---

## Quick Diagnostic Commands

**Check if ports are actually listening:**
```powershell
netstat -ano | findstr ":3000 :3001"
```

**Check Node processes:**
```powershell
Get-Process node -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, Path
```

**Check if services respond (quick test):**
```powershell
Test-NetConnection -ComputerName localhost -Port 3000
Test-NetConnection -ComputerName localhost -Port 3001
```

**Check Vite config conflicts:**
```powershell
# Read vite.config.ts and check for port settings
Get-Content apps/web/vite.config.ts | Select-String -Pattern "port"
```

---

## Expected Final State

After successful startup:

1. **Port 3000:** Vite dev server listening
   - Test: `Invoke-WebRequest http://localhost:3000/` returns HTML
   - Browser shows styled UI (not raw HTML)

2. **Port 3001:** Express API server listening
   - Test: `Invoke-WebRequest http://localhost:3001/health` returns `{"status":"ok"}`
   - Test: `Invoke-RestMethod http://localhost:3001/agents` returns JSON array

3. **Both terminals show:**
   - API: "API server running on http://localhost:3001"
   - Web: "Local: http://localhost:3000/"

If you reach this state, ports are working correctly!

