import { OrderIntent } from '@domain';
import { AgentInput, IAgentStrategy, FractionalKellyAgentConfig } from './types';

/**
 * FractionalKellyAgent: Uses fractional Kelly criterion for position sizing.
 *
 * Kelly Criterion Formula (simplified for binary outcomes):
 *   kellyPct = (p * (b + 1) - 1) / b
 *   where:
 *     p = probability of winning (model probability)
 *     b = odds (1/price - 1)
 *
 * For binary markets:
 *   - If buying YES at price P, we win (1 - P) if correct, lose P if wrong
 *   - Odds b = (1 - P) / P = (1/P) - 1
 *   - Kelly = (p * (1/P) - 1) / ((1/P) - 1) = (p/P - 1) / ((1-P)/P) = (p - P) / (1 - P)
 *
 * Simplified: kellyPct = (p_model - price) / (1 - price)
 *
 * We use fractional Kelly: stakePct = kellyFraction * kellyPct
 * Only place orders if edge >= edgeFloorPct
 */
export class FractionalKellyAgent implements IAgentStrategy {
  private config: FractionalKellyAgentConfig;

  constructor(config: FractionalKellyAgentConfig) {
    this.config = config;
  }

  decide(input: AgentInput): OrderIntent[] {
    const intents: OrderIntent[] = [];

    for (const market of input.markets) {
      // Only consider open markets
      if (market.status !== 'open') {
        continue;
      }

      // Calculate market probability from YES outcome
      const pMarket = market.yes.impliedProb / 100;

      // Apply bias to get model probability
      const pModel = Math.max(0, Math.min(1, pMarket + this.config.biasPct / 100));

      // Calculate edge
      const edge = pModel - pMarket;
      const edgePct = edge * 100;

      // Check if edge meets floor threshold
      if (edgePct < this.config.edgeFloorPct) {
        continue; // Edge too small
      }

      // Determine price to use (bestAsk preferred, fallback to lastTradedPrice, then price)
      const bestAsk = market.yes.bestAsk;
      const lastTraded = market.yes.lastTradedPrice;
      const fallbackPrice = market.yes.price;

      const askPrice = bestAsk ?? lastTraded ?? fallbackPrice;

      // Skip if no valid price available or price is 1.0 (no upside)
      if (askPrice === undefined || askPrice <= 0 || askPrice >= 1) {
        continue;
      }

      // Calculate Kelly percentage
      // Kelly = (p_model - price) / (1 - price)
      // Clamp to [0, 1] to avoid negative or excessive positions
      const kellyPct = Math.max(0, Math.min(1, (pModel - askPrice) / (1 - askPrice)));

      // Apply fractional Kelly
      const stakePct = this.config.kellyFraction * kellyPct * 100;

      // Skip if stake percentage is too small (less than 0.1%)
      if (stakePct < 0.1) {
        continue;
      }

      // Calculate stake amount
      const stakeAmount = (stakePct / 100) * input.state.bankroll;

      // Calculate shares
      const shares = Math.max(1, Math.floor(stakeAmount / askPrice));

      // Create order intent
      const intent: OrderIntent = {
        marketId: market.id,
        side: 'BUY',
        outcome: 'YES',
        shares,
        limitPrice: askPrice,
        reason: `Fractional Kelly: ${(this.config.kellyFraction * 100).toFixed(0)}% of ${(kellyPct * 100).toFixed(2)}% Kelly (edge: ${edgePct.toFixed(2)}%)`,
        modelProb: pModel * 100,
        marketProb: pMarket * 100,
        edgePct,
        stakePct,
      };

      intents.push(intent);
    }

    return intents;
  }
}

