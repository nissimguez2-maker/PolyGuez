import { z } from 'zod';

/**
 * Side of an outcome in a binary market
 */
export const OutcomeSideSchema = z.enum(['YES', 'NO']);
export type OutcomeSide = z.infer<typeof OutcomeSideSchema>;

/**
 * Side of an order (buy or sell)
 */
export const OrderSideSchema = z.enum(['BUY', 'SELL']);
export type OrderSide = z.infer<typeof OrderSideSchema>;

/**
 * Quote information for a single outcome (YES or NO)
 */
export const OutcomeQuoteSchema = z.object({
  /** Outcome side (YES or NO) */
  side: OutcomeSideSchema,
  /** Current price (0.0 to 1.0) */
  price: z.number().min(0).max(1),
  /** Implied probability (0 to 100) */
  impliedProb: z.number().min(0).max(100),
  /** Best bid price (0.0 to 1.0) */
  bestBid: z.number().min(0).max(1).optional(),
  /** Best ask price (0.0 to 1.0) */
  bestAsk: z.number().min(0).max(1).optional(),
  /** Last traded price (0.0 to 1.0) */
  lastTradedPrice: z.number().min(0).max(1).optional(),
  /** 24-hour trading volume in shares */
  volume24h: z.number().nonnegative().optional(),
});
export type OutcomeQuote = z.infer<typeof OutcomeQuoteSchema>;

/**
 * Complete snapshot of a binary market at a point in time
 */
export const MarketSnapshotSchema = z.object({
  /** Internal market identifier */
  id: z.string(),
  /** External market identifier (from source API) */
  externalId: z.string(),
  /** Market title/question */
  title: z.string(),
  /** Market category (optional) */
  category: z.string().optional(),
  /** ISO timestamp when market resolves */
  resolvesAt: z.string().optional(),
  /** Market status */
  status: z.enum(['open', 'closed', 'resolved', 'suspended']),
  /** Token ID for YES outcome */
  yesTokenId: z.string(),
  /** Token ID for NO outcome */
  noTokenId: z.string(),
  /** Quote data for YES outcome */
  yes: OutcomeQuoteSchema,
  /** Quote data for NO outcome */
  no: OutcomeQuoteSchema,
  /** ISO timestamp of last update */
  lastUpdated: z.string(),
});
export type MarketSnapshot = z.infer<typeof MarketSnapshotSchema>;

/**
 * Position in a market
 */
export const PositionSchema = z.object({
  /** Market identifier */
  marketId: z.string(),
  /** Outcome side (YES or NO) */
  outcome: OutcomeSideSchema,
  /** Number of shares held */
  shares: z.number().nonnegative(),
  /** Average entry price (0.0 to 1.0) */
  avgEntryPrice: z.number().min(0).max(1),
  /** Realized profit/loss */
  realizedPnl: z.number(),
  /** Unrealized profit/loss */
  unrealizedPnl: z.number(),
});
export type Position = z.infer<typeof PositionSchema>;

/**
 * State of an agent at a point in time
 */
export const AgentStateSchema = z.object({
  /** Unique agent identifier */
  agentId: z.string(),
  /** Agent name */
  name: z.string(),
  /** Strategy type identifier */
  strategyType: z.string(),
  /** Current bankroll */
  bankroll: z.number().nonnegative(),
  /** Starting bankroll */
  startBankroll: z.number().positive(),
  /** Total profit/loss */
  pnlTotal: z.number(),
  /** Open positions */
  openPositions: z.array(PositionSchema),
  /** Maximum risk per trade as percentage of bankroll */
  maxRiskPerTradePct: z.number().min(0).max(100),
  /** Maximum total exposure as percentage of bankroll */
  maxExposurePct: z.number().min(0).max(100),
  /** Agent status */
  status: z.enum(['running', 'paused']),
  /** ISO timestamp of state snapshot */
  timestamp: z.string(),
});
export type AgentState = z.infer<typeof AgentStateSchema>;

/**
 * Intent to place an order
 */
export const OrderIntentSchema = z.object({
  /** Market identifier */
  marketId: z.string(),
  /** Order side (BUY or SELL) */
  side: OrderSideSchema,
  /** Outcome side (YES or NO) */
  outcome: OutcomeSideSchema,
  /** Number of shares */
  shares: z.number().positive(),
  /** Limit price (0.0 to 1.0) - optional for market orders */
  limitPrice: z.number().min(0).max(1).optional(),
  /** Reason for the order */
  reason: z.string().optional(),
  /** Model's probability estimate (0 to 100) */
  modelProb: z.number().min(0).max(100).optional(),
  /** Market's implied probability (0 to 100) */
  marketProb: z.number().min(0).max(100).optional(),
  /** Calculated edge percentage */
  edgePct: z.number().optional(),
  /** Stake as percentage of bankroll */
  stakePct: z.number().min(0).max(100).optional(),
});
export type OrderIntent = z.infer<typeof OrderIntentSchema>;
