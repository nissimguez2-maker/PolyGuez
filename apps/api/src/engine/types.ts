import { AgentState, MarketSnapshot, OrderIntent } from '@domain';

/**
 * Result of a filled trade
 */
export interface TradeFill {
  /** Agent identifier */
  agentId: string;
  /** Market identifier */
  marketId: string;
  /** Order side (BUY or SELL) */
  side: 'BUY' | 'SELL';
  /** Outcome side (YES or NO) */
  outcome: 'YES' | 'NO';
  /** Number of shares filled */
  shares: number;
  /** Fill price (0.0 to 1.0) */
  price: number;
  /** ISO timestamp of fill */
  timestamp: string;
  /** Realized PnL from this fill (if position was reduced) */
  realizedPnlOnFill: number;
}

/**
 * Result of applying order intents to agent state
 */
export interface ApplyOrderIntentsResult {
  /** Updated agent state */
  newState: AgentState;
  /** All fills that occurred */
  fills: TradeFill[];
  /** Rejected intents with reasons */
  rejected: Array<{ intent: OrderIntent; reason: string }>;
}

