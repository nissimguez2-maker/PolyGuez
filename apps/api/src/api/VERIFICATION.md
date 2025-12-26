# REST API Implementation - Chain of Verification

## 1. Initial: Endpoints & Stores

### Endpoints Overview:

| Endpoint | Method | Stores Used | Description |
|----------|--------|-------------|-------------|
| `/health` | GET | None | Health check |
| `/agents` | GET | StateStore | List all agents |
| `/agents/:id` | GET | StateStore | Get agent by ID |
| `/agents/:id/equity` | GET | StateStore, EquityStore | Get equity history |
| `/agents/:id/trades` | GET | StateStore, LogStore | Get trades with pagination |
| `/agents/:id/control` | POST | StateStore | Start/pause agent |
| `/agents/:id/config` | GET | StateStore | Get agent config |
| `/agents/:id/config` | PATCH | StateStore | Update agent config |
| `/replay` | GET | StateStore, EquityStore, LogStore | Get replay data |

## 2. Verification Questions & Answers

### Q1: Hva returneres hvis agentId ikke finnes?
**A:** 404 Not Found med error message
```typescript
// Handler: apps/api/src/api/routes.ts
if (!state) {
  return res.status(404).json({ error: `Agent ${params.id} not found` });
}
```
**Referanse:** Alle endpoints som krever agentId sjekker eksistens først.

### Q2: Hva hvis request body/query er ugyldig?
**A:** 400 Bad Request med Zod validation errors
```typescript
// Example: apps/api/src/api/routes.ts
catch (error) {
  if (error instanceof z.ZodError) {
    return res.status(400).json({ error: 'Invalid request', details: error.errors });
  }
}
```
**Referanse:** Alle endpoints validerer input med Zod schemas.

### Q3: Hva hvis ekstern fetch feiler (MarketData)?
**A:** 503 Service Unavailable (håndteres i errorHandler)
```typescript
// apps/api/src/api/errorHandler.ts
if (error.message.includes('fetch') || error.message.includes('network')) {
  res.status(503).json({ 
    error: 'External service unavailable',
    message: 'Failed to fetch data from external service',
  });
}
```
**Referanse:** Error handler middleware fanger eksterne feil.

### Q4: Hva hvis cursor er ugyldig i pagination?
**A:** Cursor valideres som optional string, parses til number. Hvis ugyldig, brukes 0 som default.
```typescript
// apps/api/src/api/routes.ts - GET /agents/:id/trades
let startIndex = 0;
if (query.cursor) {
  const parsedCursor = parseInt(query.cursor, 10);
  if (!isNaN(parsedCursor) && parsedCursor >= 0) {
    startIndex = parsedCursor;
  }
}
```
**Referanse:** Trades endpoint håndterer ugyldig cursor gracefully.

### Q5: Hva hvis undefined verdier bubles til client?
**A:** Alle responses er eksplisitt strukturert, null brukes i stedet for undefined.
```typescript
// Example: apps/api/src/api/routes.ts - GET /replay
res.json({
  agentId: query.agentId,
  from: query.from || null,  // Explicit null instead of undefined
  to: query.to || null,
  equity,
  trades,
  decisions,
});
```
**Referanse:** Alle endpoints returnerer eksplisitte JSON-strukturer.

## 3. Patch Summary

### Files Created:
1. `apps/api/src/api/validation.ts` - Zod validation schemas
2. `apps/api/src/api/routes.ts` - All API route handlers
3. `apps/api/src/api/errorHandler.ts` - Error handling middleware
4. `apps/api/src/api/VERIFICATION.md` - This document

### Files Modified:
1. `apps/api/src/index.ts` - Use API routes and error handler

### Key Features:
- ✅ All inputs validated with Zod
- ✅ Proper HTTP status codes (404, 400, 500, 503)
- ✅ Pagination with limit + cursor (index-based)
- ✅ No undefined in responses (explicit null)
- ✅ Error handling middleware for external errors
- ✅ Domain types used in responses (AgentState, EquityEntry, etc.)

## 4. Final: Curl Examples

### Health Check
```bash
curl http://localhost:3001/health
```
**Expected:** `{"status":"ok","timestamp":"2024-..."}`

### List All Agents
```bash
curl http://localhost:3001/agents
```
**Expected:** `{"agents":[{"id":"agent-1","name":"FlatValue Agent","status":"paused",...},...]}`

### Get Agent by ID
```bash
curl http://localhost:3001/agents/agent-1
```
**Expected:** Full AgentState object

### Get Non-existent Agent (404)
```bash
curl http://localhost:3001/agents/nonexistent
```
**Expected:** `{"error":"Agent nonexistent not found"}` (404)

### Get Equity History
```bash
curl "http://localhost:3001/agents/agent-1/equity"
curl "http://localhost:3001/agents/agent-1/equity?from=2024-01-01T00:00:00Z&to=2024-12-31T23:59:59Z"
```
**Expected:** `{"equity":[...]}`

### Get Trades with Pagination
```bash
# First page
curl "http://localhost:3001/agents/agent-1/trades?limit=10"

# Next page using cursor
curl "http://localhost:3001/agents/agent-1/trades?limit=10&cursor=10"
```
**Expected:** 
```json
{
  "trades": [...],
  "pagination": {
    "limit": 10,
    "cursor": "0",
    "nextCursor": "10",
    "hasMore": true,
    "total": 25
  }
}
```

### Start Agent
```bash
curl -X POST http://localhost:3001/agents/agent-1/control \
  -H "Content-Type: application/json" \
  -d '{"action":"start"}'
```
**Expected:** `{"message":"Agent agent-1 started","state":{...}}`

### Pause Agent
```bash
curl -X POST http://localhost:3001/agents/agent-1/control \
  -H "Content-Type: application/json" \
  -d '{"action":"pause"}'
```
**Expected:** `{"message":"Agent agent-1 paused","state":{...}}`

### Invalid Control Action (400)
```bash
curl -X POST http://localhost:3001/agents/agent-1/control \
  -H "Content-Type: application/json" \
  -d '{"action":"invalid"}'
```
**Expected:** `{"error":"Invalid request","details":[...]}` (400)

### Get Agent Config
```bash
curl http://localhost:3001/agents/agent-1/config
```
**Expected:** 
```json
{
  "agentId": "agent-1",
  "strategyType": "flatValue",
  "strategyConfig": {...},
  "maxRiskPerTradePct": 5,
  "maxExposurePct": 20,
  "name": "FlatValue Agent"
}
```

### Update Agent Config
```bash
curl -X PATCH http://localhost:3001/agents/agent-1/config \
  -H "Content-Type: application/json" \
  -d '{"maxRiskPerTradePct":10,"maxExposurePct":30}'
```
**Expected:** `{"message":"Agent agent-1 config updated","state":{...}}`

### Get Replay Data
```bash
curl "http://localhost:3001/replay?agentId=agent-1"
curl "http://localhost:3001/replay?agentId=agent-1&from=2024-01-01T00:00:00Z&to=2024-12-31T23:59:59Z"
```
**Expected:**
```json
{
  "agentId": "agent-1",
  "from": null,
  "to": null,
  "equity": [...],
  "trades": [...],
  "decisions": [...]
}
```

### Invalid Query Parameters (400)
```bash
curl "http://localhost:3001/replay?agentId="
```
**Expected:** `{"error":"Invalid request","details":[...]}` (400)

