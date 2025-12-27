# Tick Loop Implementation - Chain of Verification

## 1. Initial: Tick Pipeline Description

The tick loop pipeline works as follows:

1. **Market Data Fetching**: `MarketDataService.getAllMarketSnapshots()` fetches all available market snapshots
2. **Agent Processing Loop**: For each agent in StateStore:
   - Check if agent is paused → skip if paused
   - Get agent state and strategy config
   - Create strategy instance via `AgentRegistry.createStrategy()`
   - Call `strategy.decide({ state, markets })` to get order intents
   - Apply intents via `applyOrderIntents(state, markets, intents)`
   - Update StateStore with new state
   - Calculate equity (bankroll + unrealized PnL) and append to EquityStore
   - Log decision to LogStore with metadata
   - Log each fill to LogStore with explainability from matching intent

3. **Scheduler**: Runs tick() at regular intervals (default 60s) with overlap guard

## 2. Verification Questions & Answers

### Q1: Hva hvis snapshots er tomme?
**A:** Håndtert i `AgentRunner.tick()` linje 47-50:
- Sjekker `if (snapshots.length === 0)`
- Logger warning og returnerer tidlig
- Ingen crash, neste tick fortsetter normalt

**Referanse:** `apps/api/src/runner/AgentRunner.ts:47-50`

### Q2: Hva hvis MarketData feiler?
**A:** Håndtert i `AgentRunner.tick()` linje 38-44:
- Try-catch rundt `getAllMarketSnapshots()`
- Logger error og returnerer tidlig
- Ingen crash, server fortsetter, neste tick prøver igjen

**Referanse:** `apps/api/src/runner/AgentRunner.ts:38-44`

### Q3: Hva hvis strategy.decide() kaster error?
**A:** Håndtert i `AgentRunner.processAgent()` linje 103-108:
- Try-catch rundt `strategy.decide()`
- Logger error for spesifikk agent
- Returnerer tidlig (continue med neste agent)
- Isolerer feil: én agent-feil stopper ikke andre agenter

**Referanse:** `apps/api/src/runner/AgentRunner.ts:103-108`

### Q4: Hva hvis tick loop overlapper (tidligere tick ikke ferdig)?
**A:** Håndtert i `Scheduler.runTick()` linje 55-59:
- Overlap guard: `isRunning` boolean flag
- Sjekker flag før tick starter
- Hvis flag er true → logger warning og hopper over tick
- Flag settes i finally block for å garantere release

**Referanse:** `apps/api/src/runner/scheduler.ts:54-73`

### Q5: Hva hvis en agent kaster error under processing?
**A:** Håndtert i `AgentRunner.tick()` linje 56-62:
- Try-catch rundt `processAgent()` for hver agent
- Logger error med agentId
- Continue med neste agent
- Isolerer feil: én agent-feil stopper ikke andre agenter

**Referanse:** `apps/api/src/runner/AgentRunner.ts:56-62`

## 3. Patch Summary

### Files Created:
1. `apps/api/src/stores/LogStore.ts` - Logging store for decisions and trades
2. `apps/api/src/runner/AgentRunner.ts` - Main tick loop orchestrator
3. `apps/api/src/runner/scheduler.ts` - Interval scheduler with overlap guard
4. `apps/api/src/runner/seedAgents.ts` - Initialize 3 agents with different strategies
5. `apps/api/src/runner/index.ts` - Module exports

### Files Modified:
1. `apps/api/src/stores/StateStore.ts` - Added strategy config storage methods
2. `apps/api/src/index.ts` - Initialize stores, runner, scheduler, and seed agents

### Key Features:
- ✅ Overlap guard (mutex) prevents concurrent ticks
- ✅ MarketData failures don't crash server
- ✅ Agent errors are isolated (one agent failure doesn't stop others)
- ✅ No logging inside engine (all logging in runner)
- ✅ Equity tracking (bankroll + unrealized PnL)
- ✅ Decision and trade logging with explainability

## 4. Final: Commands & Expected Output

### Start Server:
```bash
pnpm -C apps/api dev
```

### Expected Logs:
```
[Scheduler] Starting with interval 60s
[seedAgents] Seeded 3 agents: agent-1, agent-2, agent-3
API server running on http://localhost:3001
Scheduler started with 60s interval
```

### After First Tick (if markets available):
- No errors (agents are paused initially)
- If you set an agent status to "running", you should see:
  - Decision logs in LogStore
  - Equity points in EquityStore (if trades occur)
  - Trade logs in LogStore (if fills occur)

### To Test with Active Agent:
1. Set agent status to "running" (via API endpoint or direct state update)
2. Wait for next tick (60s interval)
3. Check equity points growing in EquityStore
4. Check decision/trade logs in LogStore

### Error Scenarios (should not crash):
- MarketData API failure → logs error, continues next tick
- Empty snapshots → logs warning, continues next tick
- Strategy error → logs error for that agent, continues with others
- Overlapping ticks → skips tick, logs warning

