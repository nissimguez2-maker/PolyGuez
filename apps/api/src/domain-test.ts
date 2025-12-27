/**
 * Compile-time verification that @domain imports work correctly
 * This file should compile without errors if domain package is set up correctly
 */

import {
  OutcomeSide,
  OrderSide,
  OutcomeQuote,
  MarketSnapshot,
  Position,
  AgentState,
  OrderIntent,
  OutcomeSideSchema,
  OrderSideSchema,
  OutcomeQuoteSchema,
  MarketSnapshotSchema,
  PositionSchema,
  AgentStateSchema,
  OrderIntentSchema,
} from '@domain';

// Type checks
const testOutcomeSide: OutcomeSide = 'YES';
const testOrderSide: OrderSide = 'BUY';

const testQuote: OutcomeQuote = {
  side: 'YES',
  price: 0.65,
  impliedProb: 65,
  bestBid: 0.64,
  bestAsk: 0.66,
};

const testMarket: MarketSnapshot = {
  id: 'market-1',
  externalId: 'ext-123',
  title: 'Test Market',
  status: 'open',
  yesTokenId: 'token-yes',
  noTokenId: 'token-no',
  yes: testQuote,
  no: {
    side: 'NO',
    price: 0.35,
    impliedProb: 35,
  },
  lastUpdated: new Date().toISOString(),
};

const testPosition: Position = {
  marketId: 'market-1',
  outcome: 'YES',
  shares: 100,
  avgEntryPrice: 0.60,
  realizedPnl: 0,
  unrealizedPnl: 5,
};

const testAgentState: AgentState = {
  agentId: 'agent-1',
  name: 'Test Agent',
  strategyType: 'momentum',
  bankroll: 1000,
  startBankroll: 1000,
  pnlTotal: 0,
  openPositions: [testPosition],
  maxRiskPerTradePct: 5,
  maxExposurePct: 20,
  status: 'running',
  timestamp: new Date().toISOString(),
};

const testOrderIntent: OrderIntent = {
  marketId: 'market-1',
  side: 'BUY',
  outcome: 'YES',
  shares: 50,
  limitPrice: 0.65,
  reason: 'Model edge detected',
  modelProb: 70,
  marketProb: 65,
  edgePct: 5,
  stakePct: 5,
};

// Runtime validation checks
const validatedOutcome = OutcomeSideSchema.parse('YES');
const validatedOrder = OrderSideSchema.parse('BUY');
const validatedQuote = OutcomeQuoteSchema.parse(testQuote);
const validatedMarket = MarketSnapshotSchema.parse(testMarket);
const validatedPosition = PositionSchema.parse(testPosition);
const validatedAgent = AgentStateSchema.parse(testAgentState);
const validatedIntent = OrderIntentSchema.parse(testOrderIntent);

// Export to ensure types are actually used (prevents unused variable warnings)
export {
  testOutcomeSide,
  testOrderSide,
  testQuote,
  testMarket,
  testPosition,
  testAgentState,
  testOrderIntent,
  validatedOutcome,
  validatedOrder,
  validatedQuote,
  validatedMarket,
  validatedPosition,
  validatedAgent,
  validatedIntent,
};

