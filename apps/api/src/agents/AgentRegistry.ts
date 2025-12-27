import {
  IAgentStrategy,
  FlatValueAgentConfig,
  FractionalKellyAgentConfig,
  RandomBaselineAgentConfig,
} from './types';
import { FlatValueAgent } from './FlatValueAgent';
import { FractionalKellyAgent } from './FractionalKellyAgent';
import { RandomBaselineAgent } from './RandomBaselineAgent';

/**
 * Supported strategy types
 */
export type StrategyType = 'flatValue' | 'fractionalKelly' | 'randomBaseline';

/**
 * Union type of all strategy configs
 */
export type StrategyConfig =
  | FlatValueAgentConfig
  | FractionalKellyAgentConfig
  | RandomBaselineAgentConfig;

/**
 * Registry for creating agent strategies
 */
export class AgentRegistry {
  /**
   * Create a strategy instance from type and config
   * @param strategyType Type of strategy to create
   * @param config Strategy configuration
   * @returns Strategy instance
   */
  static createStrategy(
    strategyType: StrategyType,
    config: StrategyConfig
  ): IAgentStrategy {
    switch (strategyType) {
      case 'flatValue':
        return new FlatValueAgent(config as FlatValueAgentConfig);
      case 'fractionalKelly':
        return new FractionalKellyAgent(config as FractionalKellyAgentConfig);
      case 'randomBaseline':
        return new RandomBaselineAgent(config as RandomBaselineAgentConfig);
      default:
        throw new Error(`Unknown strategy type: ${strategyType}`);
    }
  }
}

