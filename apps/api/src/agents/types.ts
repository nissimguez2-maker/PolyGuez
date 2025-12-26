import { AgentState, MarketSnapshot, OrderIntent } from '@domain';

/**
 * Input to an agent strategy for decision making
 */
export interface AgentInput {
  /** Current agent state */
  state: AgentState;
  /** Available market snapshots */
  markets: MarketSnapshot[];
}

/**
 * Strategy interface that all agent strategies must implement
 */
export interface IAgentStrategy {
  /**
   * Decide on order intents based on current state and available markets
   * @param input Agent input containing state and markets
   * @returns Array of order intents (can be empty)
   */
  decide(input: AgentInput): OrderIntent[];
}

/**
 * Configuration for FlatValueAgent
 */
export interface FlatValueAgentConfig {
  /** Minimum edge percentage required to place an order (0-100) */
  edgeThresholdPct: number;
  /** Stake as percentage of bankroll (0-100) */
  stakePct: number;
  /** Bias to add to market probability (can be negative) */
  biasPct: number;
}

/**
 * Configuration for FractionalKellyAgent
 */
export interface FractionalKellyAgentConfig {
  /** Fraction of Kelly criterion to use (0-1, typically 0.25-0.5) */
  kellyFraction: number;
  /** Minimum edge percentage required (0-100) */
  edgeFloorPct: number;
  /** Bias to add to market probability (can be negative) */
  biasPct: number;
}

/**
 * Configuration for RandomBaselineAgent
 */
export interface RandomBaselineAgentConfig {
  /** Probability of placing an order per market tick (0-1) */
  chancePerTick: number;
  /** Stake as percentage of bankroll (0-100) */
  stakePct: number;
}

