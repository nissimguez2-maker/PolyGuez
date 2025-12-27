import { AgentState } from '@domain';
import { IStateStore } from '../stores/StateStore';
import { StrategyConfig } from '../agents/AgentRegistry';

/**
 * Seed initial agents with different strategies
 */
export function seedAgents(stateStore: IStateStore): void {
  const timestamp = new Date().toISOString();
  
  // DEV mode: Force trades for testing (DEV_FORCE_TRADES=true)
  const devForceTrades = process.env.DEV_FORCE_TRADES === 'true';

  // Agent 1: FlatValueAgent
  const agent1Id = 'agent-1';
  const agent1State: AgentState = {
    agentId: agent1Id,
    name: 'FlatValue Agent',
    strategyType: 'flatValue',
    bankroll: 100,
    startBankroll: 100,
    pnlTotal: 0,
    openPositions: [],
    maxRiskPerTradePct: 5,
    maxExposurePct: 20,
    status: devForceTrades ? 'running' : 'paused', // Auto-start in dev mode
    timestamp,
  };
  const agent1Config: StrategyConfig = devForceTrades
    ? {
        // DEV mode: Extremely low threshold to always trigger trades
        edgeThresholdPct: -100, // Negative threshold = always passes
        stakePct: 0.5, // Small stake (0.5% of bankroll)
        biasPct: 20, // +20% bias to create positive edge
      }
    : {
        // Production mode: Normal thresholds
        edgeThresholdPct: 2, // 2% edge required
        stakePct: 5, // 5% of bankroll per trade
        biasPct: 0, // No bias
      };

  stateStore.setAgentState(agent1Id, agent1State);
  stateStore.setStrategyConfig(agent1Id, agent1Config);
  
  if (devForceTrades) {
    console.log(`[seedAgents] 🔧 DEV_FORCE_TRADES enabled - agent-1 configured for forced trades`);
  }

  // Agent 2: FractionalKellyAgent
  const agent2Id = 'agent-2';
  const agent2State: AgentState = {
    agentId: agent2Id,
    name: 'FractionalKelly Agent',
    strategyType: 'fractionalKelly',
    bankroll: 100,
    startBankroll: 100,
    pnlTotal: 0,
    openPositions: [],
    maxRiskPerTradePct: 10,
    maxExposurePct: 30,
    status: 'paused', // Initially paused
    timestamp,
  };
  const agent2Config: StrategyConfig = {
    kellyFraction: 0.25, // 25% of Kelly
    edgeFloorPct: 1, // 1% minimum edge
    biasPct: 0, // No bias
  };

  stateStore.setAgentState(agent2Id, agent2State);
  stateStore.setStrategyConfig(agent2Id, agent2Config);

  // Agent 3: RandomBaselineAgent
  const agent3Id = 'agent-3';
  const agent3State: AgentState = {
    agentId: agent3Id,
    name: 'Random Baseline Agent',
    strategyType: 'randomBaseline',
    bankroll: 100,
    startBankroll: 100,
    pnlTotal: 0,
    openPositions: [],
    maxRiskPerTradePct: 3,
    maxExposurePct: 15,
    status: 'paused', // Initially paused
    timestamp,
  };
  const agent3Config: StrategyConfig = {
    chancePerTick: 0.1, // 10% chance per tick
    stakePct: 3, // 3% of bankroll per trade
  };

  stateStore.setAgentState(agent3Id, agent3State);
  stateStore.setStrategyConfig(agent3Id, agent3Config);

  console.log(`[seedAgents] Seeded 3 agents: ${agent1Id}, ${agent2Id}, ${agent3Id}`);
}

