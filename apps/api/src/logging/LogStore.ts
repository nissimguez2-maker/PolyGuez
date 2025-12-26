import { DecisionLog, TradeLog } from './types';

/**
 * Pagination options for querying logs
 */
export interface PaginationOptions {
  /** Number of entries per page */
  limit: number;
  /** Offset for pagination */
  offset: number;
}

/**
 * Paginated result
 */
export interface PaginatedResult<T> {
  /** The data items */
  items: T[];
  /** Total count of items (before pagination) */
  total: number;
  /** Current offset */
  offset: number;
  /** Limit used */
  limit: number;
  /** Whether there are more items */
  hasMore: boolean;
}

/**
 * Interface for log storage
 */
export interface ILogStore {
  /** Add a decision log entry */
  addDecision(log: DecisionLog): void;
  /** Add a trade log entry */
  addTrade(log: TradeLog): void;
  /** Query decision logs */
  queryDecisions(
    agentId: string,
    from?: string,
    to?: string,
    pagination?: PaginationOptions
  ): PaginatedResult<DecisionLog>;
  /** Query trade logs */
  queryTrades(
    agentId: string,
    from?: string,
    to?: string,
    pagination?: PaginationOptions
  ): PaginatedResult<TradeLog>;
}

/**
 * In-memory implementation of log store
 */
export class InMemoryLogStore implements ILogStore {
  private decisions: Map<string, DecisionLog[]> = new Map();
  private trades: Map<string, TradeLog[]> = new Map();

  addDecision(log: DecisionLog): void {
    const agentDecisions = this.decisions.get(log.agentId) || [];
    agentDecisions.push(log);
    // Keep decisions sorted by timestamp
    agentDecisions.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    this.decisions.set(log.agentId, agentDecisions);
  }

  addTrade(log: TradeLog): void {
    const agentTrades = this.trades.get(log.agentId) || [];
    agentTrades.push(log);
    // Keep trades sorted by timestamp
    agentTrades.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    this.trades.set(log.agentId, agentTrades);
  }

  queryDecisions(
    agentId: string,
    from?: string,
    to?: string,
    pagination?: PaginationOptions
  ): PaginatedResult<DecisionLog> {
    let agentDecisions = this.decisions.get(agentId) || [];

    // Filter by time range
    if (from || to) {
      agentDecisions = agentDecisions.filter((log) => {
        const logTime = new Date(log.timestamp).getTime();
        const fromTime = from ? new Date(from).getTime() : -Infinity;
        const toTime = to ? new Date(to).getTime() : Infinity;
        return logTime >= fromTime && logTime <= toTime;
      });
    }

    const total = agentDecisions.length;

    // Apply pagination
    if (pagination) {
      const { limit, offset } = pagination;
      agentDecisions = agentDecisions.slice(offset, offset + limit);
    }

    return {
      items: agentDecisions,
      total,
      offset: pagination?.offset || 0,
      limit: pagination?.limit || total,
      hasMore: pagination
        ? pagination.offset + pagination.limit < total
        : false,
    };
  }

  queryTrades(
    agentId: string,
    from?: string,
    to?: string,
    pagination?: PaginationOptions
  ): PaginatedResult<TradeLog> {
    let agentTrades = this.trades.get(agentId) || [];

    // Filter by time range
    if (from || to) {
      agentTrades = agentTrades.filter((log) => {
        const logTime = new Date(log.timestamp).getTime();
        const fromTime = from ? new Date(from).getTime() : -Infinity;
        const toTime = to ? new Date(to).getTime() : Infinity;
        return logTime >= fromTime && logTime <= toTime;
      });
    }

    const total = agentTrades.length;

    // Apply pagination
    if (pagination) {
      const { limit, offset } = pagination;
      agentTrades = agentTrades.slice(offset, offset + limit);
    }

    return {
      items: agentTrades,
      total,
      offset: pagination?.offset || 0,
      limit: pagination?.limit || total,
      hasMore: pagination
        ? pagination.offset + pagination.limit < total
        : false,
    };
  }
}

