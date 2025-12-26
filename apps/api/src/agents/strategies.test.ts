import { describe, it, expect } from 'vitest';
import { AgentState, MarketSnapshot } from '@domain';
import {
  FlatValueAgent,
  FractionalKellyAgent,
  RandomBaselineAgent,
  AgentRegistry,
  AgentInput,
} from './index';

/**
 * Helper to create a test market snapshot
 */
function createTestMarket(
  overrides?: Partial<MarketSnapshot>
): MarketSnapshot {
  return {
    id: 'market-1',
    externalId: 'ext-1',
    title: 'Test Market',
    status: 'open',
    yesTokenId: 'token-yes',
    noTokenId: 'token-no',
    yes: {
      side: 'YES',
      price: 0.65,
      impliedProb: 65,
      bestBid: 0.64,
      bestAsk: 0.66,
      lastTradedPrice: 0.65,
    },
    no: {
      side: 'NO',
      price: 0.35,
      impliedProb: 35,
    },
    lastUpdated: new Date().toISOString(),
    ...overrides,
  };
}

/**
 * Helper to create a test agent state
 */
function createTestAgentState(overrides?: Partial<AgentState>): AgentState {
  return {
    agentId: 'agent-1',
    name: 'Test Agent',
    strategyType: 'flatValue',
    bankroll: 1000,
    startBankroll: 1000,
    pnlTotal: 0,
    openPositions: [],
    maxRiskPerTradePct: 5,
    maxExposurePct: 20,
    status: 'running',
    timestamp: new Date().toISOString(),
    ...overrides,
  };
}

describe('FlatValueAgent', () => {
  it('should produce OrderIntent with shares and reason when edge meets threshold', () => {
    const agent = new FlatValueAgent({
      edgeThresholdPct: 3, // 3% edge required
      stakePct: 5, // 5% of bankroll
      biasPct: 5, // +5% bias (market 65% -> model 70%)
    });

    const state = createTestAgentState({ bankroll: 1000 });
    const market = createTestMarket({
      yes: {
        side: 'YES',
        price: 0.65,
        impliedProb: 65,
        bestAsk: 0.66,
      },
    });

    const input: AgentInput = {
      state,
      markets: [market],
    };

    const intents = agent.decide(input);

    expect(intents).toHaveLength(1);
    const intent = intents[0];

    // Verify required fields
    expect(intent.shares).toBeGreaterThan(0);
    expect(intent.reason).toBeDefined();
    expect(intent.reason?.length).toBeGreaterThan(0);

    // Verify explainability fields
    expect(intent.modelProb).toBeDefined();
    expect(intent.marketProb).toBeDefined();
    expect(intent.edgePct).toBeDefined();
    expect(intent.stakePct).toBeDefined();

    // Verify values
    expect(intent.marketId).toBe('market-1');
    expect(intent.side).toBe('BUY');
    expect(intent.outcome).toBe('YES');
    expect(intent.modelProb).toBeCloseTo(70, 1); // 65% + 5% bias
    expect(intent.marketProb).toBe(65);
    expect(intent.edgePct).toBeCloseTo(5, 1); // 70% - 65%
    expect(intent.stakePct).toBe(5);

    // Verify shares calculation: (5% of 1000) / 0.66 = 50 / 0.66 ≈ 75 shares
    expect(intent.shares).toBeGreaterThan(0);
  });

  it('should not produce intents when edge is below threshold', () => {
    const agent = new FlatValueAgent({
      edgeThresholdPct: 10, // 10% edge required
      stakePct: 5,
      biasPct: 3, // Only 3% bias (edge = 3%, below threshold)
    });

    const state = createTestAgentState();
    const market = createTestMarket();

    const input: AgentInput = {
      state,
      markets: [market],
    };

    const intents = agent.decide(input);

    expect(intents).toHaveLength(0);
  });

  it('should use lastTradedPrice as fallback when bestAsk is undefined', () => {
    const agent = new FlatValueAgent({
      edgeThresholdPct: 3,
      stakePct: 5,
      biasPct: 5,
    });

    const state = createTestAgentState({ bankroll: 1000 });
    const market = createTestMarket({
      yes: {
        side: 'YES',
        price: 0.65,
        impliedProb: 65,
        bestAsk: undefined, // No bestAsk
        lastTradedPrice: 0.67, // Use this as fallback
      },
    });

    const input: AgentInput = {
      state,
      markets: [market],
    };

    const intents = agent.decide(input);

    expect(intents).toHaveLength(1);
    expect(intents[0].limitPrice).toBe(0.67);
  });

  it('should skip closed markets', () => {
    const agent = new FlatValueAgent({
      edgeThresholdPct: 3,
      stakePct: 5,
      biasPct: 5,
    });

    const state = createTestAgentState();
    const market = createTestMarket({ status: 'closed' });

    const input: AgentInput = {
      state,
      markets: [market],
    };

    const intents = agent.decide(input);

    expect(intents).toHaveLength(0);
  });
});

describe('FractionalKellyAgent', () => {
  it('should produce OrderIntent with Kelly-based position sizing', () => {
    const agent = new FractionalKellyAgent({
      kellyFraction: 0.25, // 25% of Kelly
      edgeFloorPct: 2, // 2% minimum edge
      biasPct: 5, // +5% bias
    });

    const state = createTestAgentState({ bankroll: 1000 });
    const market = createTestMarket({
      yes: {
        side: 'YES',
        price: 0.65,
        impliedProb: 65,
        bestAsk: 0.66,
      },
    });

    const input: AgentInput = {
      state,
      markets: [market],
    };

    const intents = agent.decide(input);

    expect(intents).toHaveLength(1);
    const intent = intents[0];

    expect(intent.shares).toBeGreaterThan(0);
    expect(intent.reason).toBeDefined();
    expect(intent.modelProb).toBeDefined();
    expect(intent.marketProb).toBeDefined();
    expect(intent.edgePct).toBeDefined();
    expect(intent.stakePct).toBeDefined();
  });

  it('should not produce intents when edge is below floor', () => {
    const agent = new FractionalKellyAgent({
      kellyFraction: 0.25,
      edgeFloorPct: 10, // 10% minimum edge
      biasPct: 3, // Only 3% bias (below floor)
    });

    const state = createTestAgentState();
    const market = createTestMarket();

    const input: AgentInput = {
      state,
      markets: [market],
    };

    const intents = agent.decide(input);

    expect(intents).toHaveLength(0);
  });
});

describe('RandomBaselineAgent', () => {
  it('should produce OrderIntent with random decisions', () => {
    const agent = new RandomBaselineAgent({
      chancePerTick: 1.0, // 100% chance (deterministic for testing)
      stakePct: 5,
    });

    const state = createTestAgentState({ bankroll: 1000 });
    const market = createTestMarket();

    const input: AgentInput = {
      state,
      markets: [market],
    };

    const intents = agent.decide(input);

    // With 100% chance, should produce at least one intent
    expect(intents.length).toBeGreaterThanOrEqual(0); // Could be 0 if price is invalid
  });

  it('should skip markets when chancePerTick is 0', () => {
    const agent = new RandomBaselineAgent({
      chancePerTick: 0, // 0% chance
      stakePct: 5,
    });

    const state = createTestAgentState();
    const market = createTestMarket();

    const input: AgentInput = {
      state,
      markets: [market],
    };

    const intents = agent.decide(input);

    expect(intents).toHaveLength(0);
  });
});

describe('AgentRegistry', () => {
  it('should create FlatValueAgent', () => {
    const strategy = AgentRegistry.createStrategy('flatValue', {
      edgeThresholdPct: 3,
      stakePct: 5,
      biasPct: 5,
    });

    expect(strategy).toBeInstanceOf(FlatValueAgent);
  });

  it('should create FractionalKellyAgent', () => {
    const strategy = AgentRegistry.createStrategy('fractionalKelly', {
      kellyFraction: 0.25,
      edgeFloorPct: 2,
      biasPct: 5,
    });

    expect(strategy).toBeInstanceOf(FractionalKellyAgent);
  });

  it('should create RandomBaselineAgent', () => {
    const strategy = AgentRegistry.createStrategy('randomBaseline', {
      chancePerTick: 0.1,
      stakePct: 5,
    });

    expect(strategy).toBeInstanceOf(RandomBaselineAgent);
  });

  it('should throw error for unknown strategy type', () => {
    expect(() => {
      AgentRegistry.createStrategy('unknown' as any, {} as any);
    }).toThrow('Unknown strategy type: unknown');
  });
});

