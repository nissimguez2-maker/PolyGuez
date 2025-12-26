import { InMemoryStateStore } from '../stores/StateStore';
import { InMemoryEquityStore } from '../stores/EquityStore';
import { InMemoryLogStore } from '../logging/LogStore';
import { ReplayService } from './replayService';
import { AgentState } from '@domain';
import { DecisionLog, TradeLog } from '../logging/types';
import { TradeFill } from '../engine/types';

/**
 * Sanity runner to demonstrate stores, logging, and replay functionality
 */
export function runReplaySanityCheck(): void {
  console.log('=== Replay Sanity Runner ===\n');

  // Initialize stores
  const stateStore = new InMemoryStateStore();
  const equityStore = new InMemoryEquityStore();
  const logStore = new InMemoryLogStore();
  const replayService = new ReplayService(equityStore, logStore);

  // Create a dummy agent state
  const agentId = 'agent-001';
  const baseTime = new Date('2024-01-01T00:00:00Z').toISOString();

  const agentState: AgentState = {
    agentId,
    name: 'Test Agent',
    strategyType: 'flat-value',
    bankroll: 1000,
    startBankroll: 1000,
    pnlTotal: 0,
    openPositions: [],
    maxRiskPerTradePct: 5,
    maxExposurePct: 20,
    status: 'running',
    timestamp: baseTime,
  };

  stateStore.setAgentState(agentId, agentState);
  console.log('✓ Created agent state');

  // Create dummy equity entries
  const equityEntries = [
    { timestamp: baseTime, equity: 1000, bankroll: 1000, pnlTotal: 0 },
    {
      timestamp: new Date('2024-01-01T01:00:00Z').toISOString(),
      equity: 1050,
      bankroll: 1000,
      pnlTotal: 50,
    },
    {
      timestamp: new Date('2024-01-01T02:00:00Z').toISOString(),
      equity: 1100,
      bankroll: 1050,
      pnlTotal: 100,
    },
    {
      timestamp: new Date('2024-01-01T03:00:00Z').toISOString(),
      equity: 1080,
      bankroll: 1050,
      pnlTotal: 80,
    },
  ];

  for (const entry of equityEntries) {
    equityStore.append(agentId, entry);
  }
  console.log(`✓ Created ${equityEntries.length} equity entries`);

  // Create dummy decision logs
  const decisionLogs: DecisionLog[] = [
    {
      agentId,
      timestamp: new Date('2024-01-01T00:30:00Z').toISOString(),
      intents: [
        {
          marketId: 'market-1',
          side: 'BUY',
          outcome: 'YES',
          shares: 100,
          limitPrice: 0.6,
          reason: 'Model edge detected',
          modelProb: 70,
          marketProb: 60,
          edgePct: 10,
          stakePct: 5,
        },
      ],
      filledCount: 1,
      rejectedCount: 0,
    },
    {
      agentId,
      timestamp: new Date('2024-01-01T01:30:00Z').toISOString(),
      intents: [
        {
          marketId: 'market-2',
          side: 'BUY',
          outcome: 'NO',
          shares: 50,
          limitPrice: 0.4,
          reason: 'Value opportunity',
          modelProb: 35,
          marketProb: 40,
          edgePct: 5,
          stakePct: 2.5,
        },
      ],
      filledCount: 1,
      rejectedCount: 0,
    },
    {
      agentId,
      timestamp: new Date('2024-01-01T02:30:00Z').toISOString(),
      intents: [
        {
          marketId: 'market-1',
          side: 'SELL',
          outcome: 'YES',
          shares: 50,
          reason: 'Taking profit',
        },
        {
          marketId: 'market-3',
          side: 'BUY',
          outcome: 'YES',
          shares: 200,
          limitPrice: 0.55,
          reason: 'Strong signal',
          modelProb: 80,
          marketProb: 55,
          edgePct: 25,
          stakePct: 10,
        },
      ],
      filledCount: 2,
      rejectedCount: 0,
    },
  ];

  for (const log of decisionLogs) {
    logStore.addDecision(log);
  }
  console.log(`✓ Created ${decisionLogs.length} decision logs`);

  // Create dummy trade logs
  const tradeLogs: TradeLog[] = [
    {
      agentId,
      timestamp: new Date('2024-01-01T00:30:15Z').toISOString(),
      fill: {
        agentId,
        marketId: 'market-1',
        side: 'BUY',
        outcome: 'YES',
        shares: 100,
        price: 0.6,
        timestamp: new Date('2024-01-01T00:30:15Z').toISOString(),
        realizedPnlOnFill: 0,
      },
      reason: 'Model edge detected',
      modelProb: 70,
      marketProb: 60,
      edgePct: 10,
      stakePct: 5,
    },
    {
      agentId,
      timestamp: new Date('2024-01-01T01:30:20Z').toISOString(),
      fill: {
        agentId,
        marketId: 'market-2',
        side: 'BUY',
        outcome: 'NO',
        shares: 50,
        price: 0.4,
        timestamp: new Date('2024-01-01T01:30:20Z').toISOString(),
        realizedPnlOnFill: 0,
      },
      reason: 'Value opportunity',
      modelProb: 35,
      marketProb: 40,
      edgePct: 5,
      stakePct: 2.5,
    },
    {
      agentId,
      timestamp: new Date('2024-01-01T02:30:10Z').toISOString(),
      fill: {
        agentId,
        marketId: 'market-1',
        side: 'SELL',
        outcome: 'YES',
        shares: 50,
        price: 0.65,
        timestamp: new Date('2024-01-01T02:30:10Z').toISOString(),
        realizedPnlOnFill: 2.5,
      },
      reason: 'Taking profit',
    },
    {
      agentId,
      timestamp: new Date('2024-01-01T02:30:25Z').toISOString(),
      fill: {
        agentId,
        marketId: 'market-3',
        side: 'BUY',
        outcome: 'YES',
        shares: 200,
        price: 0.55,
        timestamp: new Date('2024-01-01T02:30:25Z').toISOString(),
        realizedPnlOnFill: 0,
      },
      reason: 'Strong signal',
      modelProb: 80,
      marketProb: 55,
      edgePct: 25,
      stakePct: 10,
    },
  ];

  for (const log of tradeLogs) {
    logStore.addTrade(log);
  }
  console.log(`✓ Created ${tradeLogs.length} trade logs\n`);

  // Test replay service
  const from = new Date('2024-01-01T00:00:00Z').toISOString();
  const to = new Date('2024-01-01T03:00:00Z').toISOString();

  console.log(`Fetching replay data from ${from} to ${to}...\n`);
  const replayData = replayService.getReplayData(agentId, from, to);

  // Display structured output
  console.log('=== REPLAY DATA ===\n');

  console.log(`Equity Entries (${replayData.equity.length}):`);
  replayData.equity.forEach((entry, idx) => {
    console.log(
      `  [${idx + 1}] ${entry.timestamp} | Equity: ${entry.equity} | Bankroll: ${entry.bankroll} | PnL: ${entry.pnlTotal}`
    );
  });

  console.log(`\nTrade Logs (${replayData.trades.length}):`);
  replayData.trades.forEach((trade, idx) => {
    console.log(
      `  [${idx + 1}] ${trade.timestamp} | ${trade.fill.side} ${trade.fill.shares} ${trade.fill.outcome} @ ${trade.fill.price} | PnL: ${trade.fill.realizedPnlOnFill}`
    );
    if (trade.reason) {
      console.log(`      Reason: ${trade.reason}`);
    }
    if (trade.modelProb !== undefined) {
      console.log(
        `      Model: ${trade.modelProb}% | Market: ${trade.marketProb}% | Edge: ${trade.edgePct}%`
      );
    }
  });

  console.log(`\nDecision Logs (${replayData.decisions.length}):`);
  replayData.decisions.forEach((decision, idx) => {
    console.log(
      `  [${idx + 1}] ${decision.timestamp} | Intents: ${decision.intents.length} | Filled: ${decision.filledCount} | Rejected: ${decision.rejectedCount}`
    );
    decision.intents.forEach((intent, i) => {
      console.log(
        `      Intent ${i + 1}: ${intent.side} ${intent.shares} ${intent.outcome} @ ${intent.limitPrice ?? 'MARKET'}`
      );
      if (intent.reason) {
        console.log(`        Reason: ${intent.reason}`);
      }
    });
  });

  // Test time range filtering
  console.log('\n=== TIME RANGE FILTERING TEST ===\n');
  const filteredFrom = new Date('2024-01-01T01:00:00Z').toISOString();
  const filteredTo = new Date('2024-01-01T02:00:00Z').toISOString();
  const filteredData = replayService.getReplayData(
    agentId,
    filteredFrom,
    filteredTo
  );

  console.log(
    `Filtered data from ${filteredFrom} to ${filteredTo}:`
  );
  console.log(`  Equity entries: ${filteredData.equity.length}`);
  console.log(`  Trades: ${filteredData.trades.length}`);
  console.log(`  Decisions: ${filteredData.decisions.length}`);

  // Test pagination
  console.log('\n=== PAGINATION TEST ===\n');
  const paginatedTrades = logStore.queryTrades(agentId, undefined, undefined, {
    limit: 2,
    offset: 0,
  });
  console.log(
    `Paginated trades (limit=2, offset=0): ${paginatedTrades.items.length} items, total: ${paginatedTrades.total}, hasMore: ${paginatedTrades.hasMore}`
  );

  const paginatedDecisions = logStore.queryDecisions(
    agentId,
    undefined,
    undefined,
    { limit: 1, offset: 1 }
  );
  console.log(
    `Paginated decisions (limit=1, offset=1): ${paginatedDecisions.items.length} items, total: ${paginatedDecisions.total}, hasMore: ${paginatedDecisions.hasMore}`
  );

  // Test state store operations
  console.log('\n=== STATE STORE OPERATIONS ===\n');
  const retrievedState = stateStore.getAgentState(agentId);
  console.log(`Retrieved agent: ${retrievedState?.name} (${retrievedState?.status})`);

  stateStore.setStatus(agentId, 'paused');
  const pausedState = stateStore.getAgentState(agentId);
  console.log(`After setStatus('paused'): ${pausedState?.status}`);

  stateStore.updateConfig(agentId, { maxRiskPerTradePct: 10 });
  const updatedState = stateStore.getAgentState(agentId);
  console.log(
    `After updateConfig(maxRiskPerTradePct=10): ${updatedState?.maxRiskPerTradePct}%`
  );

  const allAgents = stateStore.listAgents();
  console.log(`All agents: ${allAgents.join(', ')}`);

  console.log('\n=== SANITY CHECK COMPLETE ===');
}

