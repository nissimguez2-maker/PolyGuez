# Dev Setup Guide

## Quick Start (Windows PowerShell)

### 1. Start Everything
```powershell
.\scripts\dev.ps1
```
Dette starter:
- API server på http://localhost:3001 (med DEV_FORCE_TRADES=true og RUNNER_ENABLED=true)
- WEB app på http://localhost:3000
- Åpner nettleser automatisk når web er klar (polling på http://localhost:3000)
- Rydder opp port 3000 og 3001 før start

### 2. Check API Health
```powershell
pnpm -C apps/api health
```
Viser health check JSON med pretty formatting.

### 3. List All Agents
```powershell
pnpm -C apps/api agents:list
```
Viser alle agents med pretty formatting.

### 4. Pretty Print Replay Data
```powershell
pnpm -C apps/api replay:agent1
```
Viser replay JSON for agent-1 med pretty formatting (Depth 20).

### 5. Chat with Agent
```powershell
pnpm -C apps/api chat:agent1 "Hva er status?"
```
Sender chat-melding til agent-1 og viser LLM-respons med pretty formatting.

**Eksempel output:**
```json
{
  "success": true,
  "mode": "mock",
  "message": "I understand you're asking about agent \"FlatValue Agent\". This is a mock response...",
  "timestamp": "2024-01-01T12:00:00.000Z",
  "agentId": "agent-1"
}
```

**Hva betyr "mode"?**
- `"mode": "mock"` - Mock response (OPENAI_API_KEY ikke satt eller ikke tilgjengelig)
- `"mode": "openai"` - Ekte LLM-respons fra OpenAI API

**Hvis du ser HTML / "Unexpected token <" feil:**
Dette betyr at frontend/API mottar HTML i stedet for JSON. Sjekk:
1. At API-serveren kjører på port 3001 (`pnpm -C apps/api health`)
2. At Vite proxy rewrite er aktiv (sjekk `apps/web/vite.config.ts` - proxy rewrite `/api` → `/`)
3. At API returnerer JSON (aldri HTML) - alle error responses har `mode: "mock"` og er JSON

## If Something Breaks

### Port Already in Use
Hvis du får "port already in use" feil:
```powershell
# Kill port 3000 (web)
Get-NetTCPConnection -LocalPort 3000 | Select-Object -ExpandProperty OwningProcess | Stop-Process -Force

# Kill port 3001 (api)
Get-NetTCPConnection -LocalPort 3001 | Select-Object -ExpandProperty OwningProcess | Stop-Process -Force
```
Eller kjør `.\scripts\dev.ps1` på nytt - den rydder automatisk opp før start.

### API Not Responding
1. Sjekk at API kjører i eget PowerShell-vindu
2. Test health endpoint:
   ```powershell
   pnpm -C apps/api health
   ```
3. Hvis feil, sjekk API-vinduet for feilmeldinger
4. Restart API: Stopp prosessen i API-vinduet (Ctrl+C) og kjør `.\scripts\dev.ps1` på nytt

### Web Not Loading / Proxy Errors
1. Sjekk at både API og WEB kjører (to separate PowerShell-vinduer)
2. Sjekk browser console (F12) for proxy-feil
3. Verifiser at API svarer:
   ```powershell
   pnpm -C apps/api health
   ```
4. Hvis API svarer men web ikke, restart web: Stopp prosessen i WEB-vinduet (Ctrl+C) og kjør `.\scripts\dev.ps1` på nytt

### "Unexpected token '<'" Error / HTML Response
Dette betyr at frontend/API mottar HTML i stedet for JSON. Sjekk:
1. At API-serveren kjører på port 3001 (`pnpm -C apps/api health`)
2. At Vite proxy rewrite er aktiv (sjekk `apps/web/vite.config.ts` - proxy rewrite `/api` → `/`)
3. At API returnerer JSON (aldri HTML) - alle error responses har `mode: "mock"` og er JSON
4. At API-rutene matcher (uten /api-prefix: `/agents`, `/replay`, `/health`, `/chat`)

Frontend kaller `/api/agents` som proxy-en rewrite til `/agents` på API-serveren.

### Smoke Test
Kjør full smoke test for å verifisere alle endpoints:
```powershell
pnpm -C apps/api smoke
```

### Raw Dev Mode (uten kill-port)
Hvis du vil kjøre API uten automatisk port-rydding:
```powershell
pnpm -C apps/api dev:raw
```
Kjører kun `tsx watch src/index.ts` uten å drepe eksisterende prosesser på port 3001.
