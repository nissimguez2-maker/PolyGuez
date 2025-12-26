import { AgentState } from '@domain';
import { StrategyConfig } from '../agents/AgentRegistry';

/**
 * Interface for agent state storage
 */
export interface IStateStore {
  /** Get agent state by ID */
  getAgentState(id: string): AgentState | undefined;
  /** Set/update agent state */
  setAgentState(id: string, state: AgentState): void;
  /** List all agent IDs */
  listAgents(): string[];
  /** Update agent status */
  setStatus(id: string, status: 'running' | 'paused'): void;
  /** Update agent configuration */
  updateConfig(
    id: string,
    config: {
      maxRiskPerTradePct?: number;
      maxExposurePct?: number;
      name?: string;
    }
  ): void;
  /** Get strategy config for an agent */
  getStrategyConfig(id: string): StrategyConfig | undefined;
  /** Set strategy config for an agent */
  setStrategyConfig(id: string, config: StrategyConfig): void;
}

/**
 * In-memory implementation of state store
 */
export class InMemoryStateStore implements IStateStore {
  private states: Map<string, AgentState> = new Map();
  private strategyConfigs: Map<string, StrategyConfig> = new Map();

  getAgentState(id: string): AgentState | undefined {
    return this.states.get(id);
  }

  setAgentState(id: string, state: AgentState): void {
    this.states.set(id, state);
  }

  listAgents(): string[] {
    return Array.from(this.states.keys());
  }

  setStatus(id: string, status: 'running' | 'paused'): void {
    const state = this.states.get(id);
    if (!state) {
      throw new Error(`Agent ${id} not found`);
    }
    this.states.set(id, { ...state, status });
  }

  updateConfig(
    id: string,
    config: {
      maxRiskPerTradePct?: number;
      maxExposurePct?: number;
      name?: string;
    }
  ): void {
    const state = this.states.get(id);
    if (!state) {
      throw new Error(`Agent ${id} not found`);
    }
    this.states.set(id, {
      ...state,
      ...(config.maxRiskPerTradePct !== undefined && {
        maxRiskPerTradePct: config.maxRiskPerTradePct,
      }),
      ...(config.maxExposurePct !== undefined && {
        maxExposurePct: config.maxExposurePct,
      }),
      ...(config.name !== undefined && { name: config.name }),
    });
  }

  getStrategyConfig(id: string): StrategyConfig | undefined {
    return this.strategyConfigs.get(id);
  }

  setStrategyConfig(id: string, config: StrategyConfig): void {
    this.strategyConfigs.set(id, config);
  }
}

