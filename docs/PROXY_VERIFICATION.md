# Proxy Rewrite Verification

## Current Configuration

**apps/web/vite.config.ts** (line 18):
```typescript
rewrite: (path) => path.replace(/^\/api/, ''),
```

This correctly removes `/api` prefix from requests.

## Verification Steps

### 1. Start Services
```powershell
.\scripts\dev.ps1
```

### 2. Open Browser DevTools
- Open http://localhost:3000
- Press F12 to open DevTools
- Go to **Network** tab

### 3. Verify Proxy Rewrite
1. Look for a request to `/api/agents` (or any `/api/*` endpoint)
2. Click on the request
3. Check the **Request URL** in the details:
   - **Expected**: `http://localhost:3001/agents` (without `/api`)
   - **Wrong**: `http://localhost:3001/api/agents` (with `/api`)

### 4. Expected Behavior
- Frontend calls: `/api/agents`
- Vite proxy rewrites to: `/agents`
- API receives: `GET /agents`
- Response: JSON with `{ agents: [...] }`

### 5. If You See HTML Instead of JSON
- Check that API server is running on port 3001
- Check Network tab: the request should go to `localhost:3001/agents` (not `/api/agents`)
- If request URL still has `/api`, the rewrite is not working

## Content-Type Check (Secondary Safety)

The Content-Type check in `apps/web/src/api/client.ts` is a **safety net**, not the primary fix:
- It catches cases where proxy fails or API is down
- It provides better error messages
- But the **real fix** is the proxy rewrite

