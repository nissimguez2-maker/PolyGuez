# Terminal Discipline Runbook (Windows)

## Standard: 3 Terminals

Always use exactly **3 terminals** for development:

1. **API:3001** - Backend API server (Express + TypeScript)
2. **WEB:3000** - Frontend dev server (Vite + React)
3. **OPS** - Operations terminal (killing processes, verification, ad-hoc commands)

---

## Terminal 1: API (Port 3001)

**Purpose:** Backend API server with agent runner and scheduler

**Start Command:**
```powershell
pnpm dev:api
```

**Or with explicit env vars:**
```powershell
$env:DEV_FORCE_TRADES="true"
$env:RUNNER_ENABLED="true"
pnpm dev:api
```

**Expected Output:**
```
[seedAgents] 🔧 DEV_FORCE_TRADES enabled - agent-1 configured for forced trades
[seedAgents] Seeded 3 agents: agent-1, agent-2, agent-3
[Server] ✅ Runner enabled - scheduler started
[Scheduler] Starting with interval 60s
API server running on http://localhost:3001
Scheduler started with 60s interval
```

**Verify:**
```powershell
Invoke-WebRequest -Uri "http://localhost:3001/health"
# Should return: {"status":"ok"}
```

**Stop:** Press `Ctrl+C` in this terminal

---

## Terminal 2: WEB (Port 3000)

**Purpose:** Frontend dev server with hot reload

**Start Command:**
```powershell
pnpm dev:web
```

**Expected Output:**
```
VITE v5.0.11  ready in XXX ms

➜  Local:   http://127.0.0.1:3000/
➜  Network: use --host to expose
➜  press h to show help
```

**Verify:**
- Open browser to `http://127.0.0.1:3000/` or `http://localhost:3000/`
- Should see styled UI (not raw HTML)

**Stop:** Press `Ctrl+C` in this terminal

---

## Terminal 3: OPS (Operations)

**Purpose:** Ad-hoc commands, verification, troubleshooting

**Common Commands:**

**Kill all Node processes:**
```powershell
Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force
```

**Check port listeners:**
```powershell
Get-NetTCPConnection -LocalPort 3000,3001 -ErrorAction SilentlyContinue | Select-Object LocalPort, State, OwningProcess | ForEach-Object { 
    $proc = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    [PSCustomObject]@{
        Port = $_.LocalPort
        State = $_.State
        PID = $_.OwningProcess
        ProcessName = if ($proc) { $proc.Name } else { "Unknown" }
    }
} | Format-Table -AutoSize
```

**Check status (shows port listeners):**
```powershell
pnpm status
```

**Quick reset (kills node + shows ports):**
```powershell
.\scripts\reset-dev.ps1
```

**Test API endpoints:**
```powershell
# Health
Invoke-WebRequest -Uri "http://localhost:3001/health"

# Agents
Invoke-RestMethod -Uri "http://localhost:3001/agents"

# Smoke test
pnpm --filter @polymarket/api smoke
```

**Test Web:**
```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:3000/"
```

---

## Startup Sequence

**Always start in this order:**

1. **Terminal 1 (API):** Start first, wait for "API server running on http://localhost:3001"
2. **Terminal 2 (WEB):** Start after API is running, wait for "Local: http://127.0.0.1:3000/"
3. **Terminal 3 (OPS):** Use for verification and troubleshooting

**Why this order?**
- WEB proxy depends on API being available on port 3001
- Starting WEB before API may cause proxy errors

---

## Shutdown Sequence

**Clean shutdown:**

1. **Terminal 2 (WEB):** Press `Ctrl+C` first
2. **Terminal 1 (API):** Press `Ctrl+C` second
3. **Terminal 3 (OPS):** Verify ports are free (see commands above)

**Force kill (if Ctrl+C doesn't work):**
```powershell
# In OPS terminal
Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force
```

---

## When "localhost refused to connect"

**Quick Checklist:**

### 1. Check if services are running
```powershell
# In OPS terminal
Get-NetTCPConnection -LocalPort 3000,3001 -ErrorAction SilentlyContinue | Select-Object LocalPort, State
```

**Expected:** Should show ports 3000 and 3001 in `Listen` state

**If empty:** Services aren't running → Start them (see Startup Sequence)

### 2. Check if ports are in wrong state
```powershell
Get-NetTCPConnection -LocalPort 3000,3001 | Where-Object {$_.State -ne "Listen"}
```

**If TIME_WAIT or ESTABLISHED:** Ports are stuck → Kill node processes and wait 5 seconds

### 3. Kill all Node processes
```powershell
Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
```

### 4. Verify ports are free
```powershell
Get-NetTCPConnection -LocalPort 3000,3001 -ErrorAction SilentlyContinue
```

**Expected:** No output (ports are free)

### 5. Check firewall
```powershell
Test-NetConnection -ComputerName localhost -Port 3000
Test-NetConnection -ComputerName localhost -Port 3001
```

**If TcpTestSucceeded: False:** Firewall may be blocking → Check Windows Firewall settings

### 6. Try IPv4 explicitly
- Use `http://127.0.0.1:3000` instead of `http://localhost:3000`
- Vite should already be configured to bind to `127.0.0.1` (see `apps/web/vite.config.ts`)

### 7. Check Vite host binding
```powershell
# In OPS terminal, check vite.config.ts
Get-Content apps/web/vite.config.ts | Select-String -Pattern "host"
```

**Expected:** Should show `host: '127.0.0.1'`

**If missing:** Vite may be binding to IPv6 → Add `host: '127.0.0.1'` to `server` config

### 8. Check for port conflicts
```powershell
netstat -ano | findstr ":3000 :3001"
```

**If other PIDs:** Kill them manually:
```powershell
Stop-Process -Id <PID> -Force
```

### 9. Nuclear option: Full reset
```powershell
# In OPS terminal
.\scripts\reset-dev.ps1
# Then restart API and WEB in order
```

---

## Port Verification Commands

**Quick port check:**
```powershell
Get-NetTCPConnection -LocalPort 3000,3001 -ErrorAction SilentlyContinue | Format-Table LocalPort, State, OwningProcess -AutoSize
```

**Detailed port check (with process names):**
```powershell
Get-NetTCPConnection -LocalPort 3000,3001 -ErrorAction SilentlyContinue | Select-Object LocalPort, State, OwningProcess | ForEach-Object { 
    $proc = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    [PSCustomObject]@{
        Port = $_.LocalPort
        State = $_.State
        PID = $_.OwningProcess
        ProcessName = if ($proc) { $proc.Name } else { "Unknown" }
        ProcessPath = if ($proc) { $proc.Path } else { "N/A" }
    }
} | Format-Table -AutoSize
```

**Check only LISTEN state (active servers):**
```powershell
Get-NetTCPConnection -LocalPort 3000,3001 -State Listen -ErrorAction SilentlyContinue | Format-Table LocalPort, State, OwningProcess -AutoSize
```

---

## Common Issues

### Issue: "Port 3000 is in use" (Vite strictPort error)
**Solution:**
```powershell
# In OPS terminal
pnpm --filter @polymarket/web kill:3000
# Or kill all node processes
Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force
```

### Issue: "EADDRINUSE" (API port 3001 in use)
**Solution:**
```powershell
# In OPS terminal
pnpm --filter @polymarket/api kill:3001
# Or kill all node processes
Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force
```

### Issue: WEB shows unstyled HTML
**Solution:**
- Check browser console (F12) for CSS loading errors
- Verify `apps/web/src/index.css` is imported in `main.tsx`
- Check Vite dev server console for PostCSS/Tailwind errors
- See `docs/TROUBLESHOOTING_PORTS.md` for detailed steps

### Issue: API returns 404
**Solution:**
- Verify API is running (check Terminal 1)
- Wait 2-3 seconds after "API server running" message
- Check API console for route registration logs
- Test health endpoint: `Invoke-WebRequest -Uri "http://localhost:3001/health"`

### Issue: Proxy errors in browser console
**Solution:**
- Verify API is running on port 3001
- Check `apps/web/vite.config.ts` proxy config
- Restart WEB terminal (Terminal 2)

---

## Do / Don't

### ✅ DO

- **DO** use exactly 3 terminals (API, WEB, OPS)
- **DO** start API before WEB (WEB proxy depends on API)
- **DO** use `pnpm dev:api` and `pnpm dev:web` from root (sets env vars automatically)
- **DO** check status with `pnpm status` before starting
- **DO** use `Ctrl+C` to stop services cleanly
- **DO** verify ports are free before starting (use `pnpm status`)
- **DO** use OPS terminal for verification and troubleshooting
- **DO** wait for "API server running" before starting WEB
- **DO** use `.\scripts\reset-dev.ps1` for quick cleanup

### ❌ DON'T

- **DON'T** mix services in one terminal
- **DON'T** start WEB before API
- **DON'T** manually set env vars (use `pnpm dev:api` which sets them automatically)
- **DON'T** kill processes with Task Manager (use `Ctrl+C` or kill scripts)
- **DON'T** restart services without checking status first
- **DON'T** run `pnpm dev` in API/WEB directories directly (use root commands)
- **DON'T** ignore port conflicts (always check with `pnpm status`)
- **DON'T** use `dev:raw` unless debugging (it skips port cleanup)

## Best Practices

1. **Always use 3 terminals** - Don't mix services in one terminal
2. **Start API before WEB** - WEB proxy depends on API
3. **Use OPS terminal for verification** - Don't clutter API/WEB terminals
4. **Kill processes cleanly** - Use `Ctrl+C` first, force kill only if needed
5. **Verify ports before starting** - Check OPS terminal if ports are free
6. **Use reset script** - `.\scripts\reset-dev.ps1` for quick cleanup
7. **Check status first** - Always run `pnpm status` before starting

---

## Dev Start Ritual (5 Steps)

**Follow this exact sequence every time:**

1. **Check Status** (OPS terminal):
   ```powershell
   pnpm status
   ```
   - Verify ports 3000/3001 are free
   - If ports are in use, kill processes first

2. **Start API** (Terminal 1):
   ```powershell
   pnpm dev:api
   ```
   - Wait for: "API server running on http://localhost:3001"
   - This automatically sets `DEV_FORCE_TRADES=true` and `RUNNER_ENABLED=true`

3. **Verify API** (OPS terminal):
   ```powershell
   Invoke-WebRequest -Uri "http://localhost:3001/health"
   ```
   - Should return: `{"status":"ok"}`

4. **Start WEB** (Terminal 2):
   ```powershell
   pnpm dev:web
   ```
   - Wait for: "Local: http://127.0.0.1:3000/"

5. **Verify WEB** (OPS terminal or browser):
   ```powershell
   Invoke-WebRequest -Uri "http://127.0.0.1:3000/"
   ```
   - Or open browser to `http://127.0.0.1:3000/`
   - Should see styled UI (not raw HTML)

**Alternative: Use helper script (starts both in separate windows):**
```powershell
pnpm dev
```
This runs `scripts/dev.ps1` which starts API and WEB in separate PowerShell windows.

---

## Dev Stop Ritual (5 Steps)

**Follow this exact sequence every time:**

1. **Stop WEB** (Terminal 2):
   - Press `Ctrl+C`
   - Wait for process to exit (should see "Terminated" or return to prompt)

2. **Stop API** (Terminal 1):
   - Press `Ctrl+C`
   - Wait for process to exit

3. **Verify Stop** (OPS terminal):
   ```powershell
   pnpm status
   ```
   - Should show ports 3000/3001 as FREE

4. **Force Kill if Needed** (OPS terminal, only if Ctrl+C didn't work):
   ```powershell
   Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force
   ```

5. **Final Verification** (OPS terminal):
   ```powershell
   pnpm status
   ```
   - Confirm both ports are free

**Quick Reset (if things are stuck):**
```powershell
.\scripts\reset-dev.ps1
```

---

## Quick Reference

**Start everything:**
```powershell
# Terminal 1
pnpm dev:api

# Terminal 2 (after API is running)
pnpm dev:web

# Terminal 3 (verification)
pnpm status
Invoke-WebRequest -Uri "http://localhost:3001/health"
Invoke-WebRequest -Uri "http://127.0.0.1:3000/"
```

**Or use helper script:**
```powershell
pnpm dev
```

**Stop everything:**
```powershell
# Terminal 2: Ctrl+C
# Terminal 1: Ctrl+C
# Terminal 3: pnpm status (verify ports are free)
```

**Reset everything:**
```powershell
# Terminal 3
.\scripts\reset-dev.ps1
```

**Check status:**
```powershell
pnpm status
```

**Verify everything:**
```powershell
# Terminal 3
pnpm status
Invoke-WebRequest -Uri "http://localhost:3001/health"
Invoke-WebRequest -Uri "http://127.0.0.1:3000/"
```

