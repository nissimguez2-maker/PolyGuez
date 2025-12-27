import { OrderIntent } from '@domain';
import { AgentInput, IAgentStrategy, RandomBaselineAgentConfig } from './types';

/**
 * RandomBaselineAgent: Random baseline strategy for comparison.
 * Places random orders with a configurable probability per market tick.
 */
export class RandomBaselineAgent implements IAgentStrategy {
  private config: RandomBaselineAgentConfig;

  constructor(config: RandomBaselineAgentConfig) {
    this.config = config;
  }

  decide(input: AgentInput): OrderIntent[] {
    const intents: OrderIntent[] = [];

    for (const market of input.markets) {
      // Only consider open markets
      if (market.status !== 'open') {
        continue;
      }

      // Random decision: place order with chancePerTick probability
      if (Math.random() >= this.config.chancePerTick) {
        continue;
      }

      // Randomly choose YES or NO
      const outcome = Math.random() < 0.5 ? 'YES' : 'NO';
      const quote = outcome === 'YES' ? market.yes : market.no;

      // Determine price to use
      const bestAsk = quote.bestAsk;
      const lastTraded = quote.lastTradedPrice;
      const fallbackPrice = quote.price;

      const askPrice = bestAsk ?? lastTraded ?? fallbackPrice;

      // Skip if no valid price available
      if (askPrice === undefined || askPrice <= 0) {
        continue;
      }

      // Calculate stake amount
      const stakeAmount = (this.config.stakePct / 100) * input.state.bankroll;

      // Calculate shares
      const shares = Math.max(1, Math.floor(stakeAmount / askPrice));

      // Create order intent
      const intent: OrderIntent = {
        marketId: market.id,
        side: 'BUY',
        outcome,
        shares,
        limitPrice: askPrice,
        reason: `Random baseline: ${(this.config.chancePerTick * 100).toFixed(1)}% chance per tick`,
        marketProb: quote.impliedProb,
        stakePct: this.config.stakePct,
      };

      intents.push(intent);
    }

    return intents;
  }
}

