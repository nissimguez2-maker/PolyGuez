import { EquityEntry, DecisionLog, TradeLog } from '../logging/types';
import { IEquityStore } from '../stores/EquityStore';
import { ILogStore } from '../logging/LogStore';

/**
 * Replay data for an agent over a time range
 */
export interface ReplayData {
  /** Equity history */
  equity: EquityEntry[];
  /** Trade logs */
  trades: TradeLog[];
  /** Decision logs */
  decisions: DecisionLog[];
}

/**
 * Replay service - provides read-only access to historical data
 */
export class ReplayService {
  constructor(
    private equityStore: IEquityStore,
    private logStore: ILogStore
  ) {}

  /**
   * Get replay data for an agent over a time range
   * @param agentId Agent identifier
   * @param from Start timestamp (ISO string)
   * @param to End timestamp (ISO string)
   * @returns Replay data containing equity, trades, and decisions
   */
  getReplayData(agentId: string, from?: string, to?: string): ReplayData {
    // Get equity history
    const equity = this.equityStore.get(agentId, from, to);

    // Get all trades (no pagination for replay)
    const tradesResult = this.logStore.queryTrades(agentId, from, to);
    const trades = tradesResult.items;

    // Get all decisions (no pagination for replay)
    const decisionsResult = this.logStore.queryDecisions(agentId, from, to);
    const decisions = decisionsResult.items;

    return {
      equity,
      trades,
      decisions,
    };
  }
}

