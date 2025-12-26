import { describe, it, expect } from 'vitest';
import { AgentState, MarketSnapshot, OrderIntent } from '@domain';
import { applyOrderIntents } from './engine';

function createMarket(
  id: string,
  yesPrice: number,
  yesBestBid?: number,
  yesBestAsk?: number,
  yesLastTraded?: number,
  noPrice?: number
): MarketSnapshot {
  return {
    id,
    externalId: `ext-${id}`,
    title: `Market ${id}`,
    status: 'open',
    yesTokenId: `token-yes-${id}`,
    noTokenId: `token-no-${id}`,
    yes: {
      side: 'YES',
      price: yesPrice,
      impliedProb: yesPrice * 100,
      bestBid: yesBestBid,
      bestAsk: yesBestAsk,
      lastTradedPrice: yesLastTraded,
    },
    no: {
      side: 'NO',
      price: noPrice ?? 1 - yesPrice,
      impliedProb: (noPrice ?? 1 - yesPrice) * 100,
    },
    lastUpdated: new Date().toISOString(),
  };
}

function createAgentState(
  agentId: string,
  bankroll: number,
  positions: AgentState['openPositions'] = [],
  maxRiskPerTradePct = 10,
  maxExposurePct = 50
): AgentState {
  return {
    agentId,
    name: `Agent ${agentId}`,
    strategyType: 'test',
    bankroll,
    startBankroll: bankroll,
    pnlTotal: 0,
    openPositions: positions,
    maxRiskPerTradePct,
    maxExposurePct,
    status: 'running',
    timestamp: new Date().toISOString(),
  };
}

describe('applyOrderIntents', () => {
  describe('Market orders', () => {
    it('should fill BUY market order at bestAsk', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'BUY',
          outcome: 'YES',
          shares: 100,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(1);
      expect(result.fills[0].price).toBe(0.61); // bestAsk
      expect(result.fills[0].shares).toBe(100);
      expect(result.rejected).toHaveLength(0);
    });

    it('should fill BUY market order at lastTradedPrice when bestAsk missing', () => {
      const market = createMarket('m1', 0.6, 0.59, undefined, 0.62);
      const state = createAgentState('agent1', 1000);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'BUY',
          outcome: 'YES',
          shares: 100,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(1);
      expect(result.fills[0].price).toBe(0.62); // lastTradedPrice
    });

    it('should fill SELL market order at bestBid', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000, [
        {
          marketId: 'm1',
          outcome: 'YES',
          shares: 100,
          avgEntryPrice: 0.55,
          realizedPnl: 0,
          unrealizedPnl: 5,
        },
      ]);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'SELL',
          outcome: 'YES',
          shares: 50,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(1);
      expect(result.fills[0].price).toBe(0.59); // bestBid
      expect(result.fills[0].shares).toBe(50);
    });

    it('should fill SELL market order at lastTradedPrice when bestBid missing', () => {
      const market = createMarket('m1', 0.6, undefined, 0.61, 0.58);
      const state = createAgentState('agent1', 1000, [
        {
          marketId: 'm1',
          outcome: 'YES',
          shares: 100,
          avgEntryPrice: 0.55,
          realizedPnl: 0,
          unrealizedPnl: 5,
        },
      ]);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'SELL',
          outcome: 'YES',
          shares: 50,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(1);
      expect(result.fills[0].price).toBe(0.58); // lastTradedPrice
    });
  });

  describe('Limit orders', () => {
    it('should fill BUY limit order when bestAsk <= limitPrice', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'BUY',
          outcome: 'YES',
          shares: 100,
          limitPrice: 0.62,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(1);
      expect(result.fills[0].price).toBe(0.61);
    });

    it('should reject BUY limit order when bestAsk > limitPrice', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'BUY',
          outcome: 'YES',
          shares: 100,
          limitPrice: 0.60,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(0);
      expect(result.rejected).toHaveLength(1);
      expect(result.rejected[0].reason).toContain('No fill price available');
    });

    it('should fill SELL limit order when bestBid >= limitPrice', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000, [
        {
          marketId: 'm1',
          outcome: 'YES',
          shares: 100,
          avgEntryPrice: 0.55,
          realizedPnl: 0,
          unrealizedPnl: 5,
        },
      ]);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'SELL',
          outcome: 'YES',
          shares: 50,
          limitPrice: 0.58,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(1);
      expect(result.fills[0].price).toBe(0.59);
    });

    it('should reject SELL limit order when bestBid < limitPrice', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000, [
        {
          marketId: 'm1',
          outcome: 'YES',
          shares: 100,
          avgEntryPrice: 0.55,
          realizedPnl: 0,
          unrealizedPnl: 5,
        },
      ]);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'SELL',
          outcome: 'YES',
          shares: 50,
          limitPrice: 0.60,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(0);
      expect(result.rejected).toHaveLength(1);
    });

    it('should use lastTradedPrice as fallback for limit orders', () => {
      const market = createMarket('m1', 0.6, undefined, undefined, 0.58);
      const state = createAgentState('agent1', 1000);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'BUY',
          outcome: 'YES',
          shares: 100,
          limitPrice: 0.60,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(1);
      expect(result.fills[0].price).toBe(0.58);
    });
  });

  describe('Realized PnL calculation', () => {
    it('should calculate realized PnL correctly on partial SELL', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000, [
        {
          marketId: 'm1',
          outcome: 'YES',
          shares: 100,
          avgEntryPrice: 0.50,
          realizedPnl: 0,
          unrealizedPnl: 10,
        },
      ]);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'SELL',
          outcome: 'YES',
          shares: 50,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(1);
      // Realized PnL = (exitPrice - entryPrice) * shares = (0.59 - 0.50) * 50 = 4.5
      expect(result.fills[0].realizedPnlOnFill).toBeCloseTo(4.5, 2);
      expect(result.newState.openPositions[0].realizedPnl).toBeCloseTo(4.5, 2);
    });

    it('should calculate realized PnL correctly on full position close', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000, [
        {
          marketId: 'm1',
          outcome: 'YES',
          shares: 100,
          avgEntryPrice: 0.50,
          realizedPnl: 0,
          unrealizedPnl: 10,
        },
      ]);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'SELL',
          outcome: 'YES',
          shares: 100,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(1);
      // Realized PnL = (0.59 - 0.50) * 100 = 9
      expect(result.fills[0].realizedPnlOnFill).toBeCloseTo(9, 2);
      expect(result.newState.openPositions).toHaveLength(0);
    });

    it('should accumulate realized PnL across multiple sells', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000, [
        {
          marketId: 'm1',
          outcome: 'YES',
          shares: 100,
          avgEntryPrice: 0.50,
          realizedPnl: 0,
          unrealizedPnl: 10,
        },
      ]);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'SELL',
          outcome: 'YES',
          shares: 30,
        },
        {
          marketId: 'm1',
          side: 'SELL',
          outcome: 'YES',
          shares: 20,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(2);
      // First sell: (0.59 - 0.50) * 30 = 2.7
      expect(result.fills[0].realizedPnlOnFill).toBeCloseTo(2.7, 2);
      // Second sell: (0.59 - 0.50) * 20 = 1.8
      expect(result.fills[1].realizedPnlOnFill).toBeCloseTo(1.8, 2);
      // Total realized: 2.7 + 1.8 = 4.5
      expect(result.newState.openPositions[0].realizedPnl).toBeCloseTo(4.5, 2);
      expect(result.newState.openPositions[0].shares).toBe(50);
    });
  });

  describe('Unrealized PnL calculation', () => {
    it('should calculate unrealized PnL correctly', () => {
      const market = createMarket('m1', 0.65); // Current price 0.65
      const state = createAgentState('agent1', 1000, [
        {
          marketId: 'm1',
          outcome: 'YES',
          shares: 100,
          avgEntryPrice: 0.60,
          realizedPnl: 0,
          unrealizedPnl: 0,
        },
      ]);

      const intents: OrderIntent[] = [];

      const result = applyOrderIntents(state, [market], intents);

      // Unrealized = (0.65 - 0.60) * 100 = 5
      expect(result.newState.openPositions[0].unrealizedPnl).toBeCloseTo(5, 2);
    });

    it('should update unrealized PnL after adding to position', () => {
      const market = createMarket('m1', 0.65, 0.64, 0.66);
      const state = createAgentState('agent1', 1000, [
        {
          marketId: 'm1',
          outcome: 'YES',
          shares: 100,
          avgEntryPrice: 0.60,
          realizedPnl: 0,
          unrealizedPnl: 5,
        },
      ]);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'BUY',
          outcome: 'YES',
          shares: 50,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      // New avg entry = (100 * 0.60 + 50 * 0.66) / 150 = 0.62
      // Unrealized = (0.65 - 0.62) * 150 = 4.5
      expect(result.newState.openPositions[0].avgEntryPrice).toBeCloseTo(0.62, 2);
      expect(result.newState.openPositions[0].unrealizedPnl).toBeCloseTo(4.5, 2);
    });
  });

  describe('Risk clipping', () => {
    it('should clip shares for maxRiskPerTradePct', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000, [], 5); // 5% max risk per trade

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'BUY',
          outcome: 'YES',
          shares: 1000, // Would be 1000 * 0.61 = 610 notional
          limitPrice: 0.62,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(1);
      // Max risk = 5% of 1000 = 50
      // Max shares = 50 / 0.61 = ~81.97, floored to 81
      expect(result.fills[0].shares).toBe(81);
      expect(result.fills[0].shares * result.fills[0].price).toBeLessThanOrEqual(50);
    });

    it('should clip shares for maxExposurePct', () => {
      const market1 = createMarket('m1', 0.6, 0.59, 0.61);
      const market2 = createMarket('m2', 0.7, 0.69, 0.71);
      const state = createAgentState('agent1', 1000, [
        {
          marketId: 'm1',
          outcome: 'YES',
          shares: 100,
          avgEntryPrice: 0.60,
          realizedPnl: 0,
          unrealizedPnl: 0,
        },
      ], 100, 20); // 100% max risk per trade (unlimited), 20% max exposure

      // Current exposure = 100 * 0.60 = 60 (using market1 current price)
      // Max exposure = 20% of 1000 = 200
      // Available = 200 - 60 = 140

      const intents: OrderIntent[] = [
        {
          marketId: 'm2',
          side: 'BUY',
          outcome: 'YES',
          shares: 1000, // Would exceed exposure limit
          limitPrice: 0.72,
        },
      ];

      // Must include market1 in markets array so calculateTotalExposure can compute current exposure
      const result = applyOrderIntents(state, [market1, market2], intents);

      expect(result.fills).toHaveLength(1);
      // Available exposure = 140, price = 0.71
      // Max shares = 140 / 0.71 = ~197, floored to 197
      expect(result.fills[0].shares).toBe(197);
    });

    it('should reject order if risk clipping results in 0 shares', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000, [
        {
          marketId: 'm1',
          outcome: 'YES',
          shares: 100,
          avgEntryPrice: 0.60,
          realizedPnl: 0,
          unrealizedPnl: 0,
        },
      ], 1, 1); // Very restrictive limits

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'BUY',
          outcome: 'YES',
          shares: 1000,
          limitPrice: 0.62,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(0);
      expect(result.rejected).toHaveLength(1);
      expect(result.rejected[0].reason).toContain('Risk limits would result in 0 shares');
    });
  });

  describe('Position management', () => {
    it('should create new position on BUY', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'BUY',
          outcome: 'YES',
          shares: 100,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.newState.openPositions).toHaveLength(1);
      expect(result.newState.openPositions[0].marketId).toBe('m1');
      expect(result.newState.openPositions[0].outcome).toBe('YES');
      expect(result.newState.openPositions[0].shares).toBe(100);
      expect(result.newState.openPositions[0].avgEntryPrice).toBe(0.61);
    });

    it('should reject SELL without existing position', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'SELL',
          outcome: 'YES',
          shares: 50,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(0);
      expect(result.rejected).toHaveLength(1);
      expect(result.rejected[0].reason).toContain('without existing position');
    });

    it('should update avgEntryPrice when adding to position', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000, [
        {
          marketId: 'm1',
          outcome: 'YES',
          shares: 100,
          avgEntryPrice: 0.50,
          realizedPnl: 0,
          unrealizedPnl: 0,
        },
      ]);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'BUY',
          outcome: 'YES',
          shares: 50,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      // New avg = (100 * 0.50 + 50 * 0.61) / 150 = 0.5367
      expect(result.newState.openPositions[0].shares).toBe(150);
      expect(result.newState.openPositions[0].avgEntryPrice).toBeCloseTo(0.5367, 4);
    });

    it('should close position when selling all shares', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000, [
        {
          marketId: 'm1',
          outcome: 'YES',
          shares: 100,
          avgEntryPrice: 0.50,
          realizedPnl: 0,
          unrealizedPnl: 0,
        },
      ]);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'SELL',
          outcome: 'YES',
          shares: 100,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.newState.openPositions).toHaveLength(0);
    });

    it('should clip SELL shares to available position', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000, [
        {
          marketId: 'm1',
          outcome: 'YES',
          shares: 50,
          avgEntryPrice: 0.50,
          realizedPnl: 0,
          unrealizedPnl: 0,
        },
      ]);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'SELL',
          outcome: 'YES',
          shares: 100, // More than available
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(1);
      expect(result.fills[0].shares).toBe(50); // Clipped to available
      expect(result.newState.openPositions).toHaveLength(0);
    });
  });

  describe('Multiple intents', () => {
    it('should process multiple intents correctly', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'BUY',
          outcome: 'YES',
          shares: 100,
        },
        {
          marketId: 'm1',
          side: 'SELL',
          outcome: 'YES',
          shares: 50,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(2);
      expect(result.newState.openPositions).toHaveLength(1);
      expect(result.newState.openPositions[0].shares).toBe(50);
    });

    it('should handle rejected and filled intents together', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000);

      // Reorder intents: SELL comes first (will be rejected - no position yet)
      // Then BUYs can proceed
      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'SELL',
          outcome: 'YES',
          shares: 50, // Will be rejected - no position yet
        },
        {
          marketId: 'm1',
          side: 'BUY',
          outcome: 'YES',
          shares: 100,
        },
        {
          marketId: 'm1',
          side: 'BUY',
          outcome: 'YES',
          shares: 50,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(2); // Two BUYs
      expect(result.rejected).toHaveLength(1); // One SELL rejected
      expect(result.newState.openPositions[0].shares).toBe(150);
    });
  });

  describe('Edge cases', () => {
    it('should reject order for non-existent market', () => {
      const market = createMarket('m1', 0.6, 0.59, 0.61);
      const state = createAgentState('agent1', 1000);

      const intents: OrderIntent[] = [
        {
          marketId: 'nonexistent',
          side: 'BUY',
          outcome: 'YES',
          shares: 100,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      expect(result.fills).toHaveLength(0);
      expect(result.rejected).toHaveLength(1);
      expect(result.rejected[0].reason).toContain('not found');
    });

    it('should handle missing price data gracefully', () => {
      const market: MarketSnapshot = {
        id: 'm1',
        externalId: 'ext-m1',
        title: 'Market m1',
        status: 'open',
        yesTokenId: 'token-yes',
        noTokenId: 'token-no',
        yes: {
          side: 'YES',
          price: 0.6,
          impliedProb: 60,
        },
        no: {
          side: 'NO',
          price: 0.4,
          impliedProb: 40,
        },
        lastUpdated: new Date().toISOString(),
      };
      const state = createAgentState('agent1', 1000);

      const intents: OrderIntent[] = [
        {
          marketId: 'm1',
          side: 'BUY',
          outcome: 'YES',
          shares: 100,
        },
      ];

      const result = applyOrderIntents(state, [market], intents);

      // Should reject because no bestAsk or lastTradedPrice
      expect(result.fills).toHaveLength(0);
      expect(result.rejected).toHaveLength(1);
    });
  });
});

