import { OrderIntent } from '@domain';
import { AgentInput, IAgentStrategy, FlatValueAgentConfig } from './types';

/**
 * FlatValueAgent: Places orders when model probability exceeds market probability
 * by a threshold, with a configurable bias adjustment.
 *
 * Logic:
 * - p_market = yes.impliedProb / 100
 * - p_model = clamp(p_market + biasPct/100, 0, 1)
 * - edge = p_model - p_market
 * - If edge >= threshold => BUY YES
 * - shares = (stakePct/100 * bankroll) / bestAskPrice (fallback: lastTradedPrice)
 */
export class FlatValueAgent implements IAgentStrategy {
  private config: FlatValueAgentConfig;

  constructor(config: FlatValueAgentConfig) {
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

      // Check if edge meets threshold
      if (edgePct < this.config.edgeThresholdPct) {
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

      // Calculate stake amount
      const stakeAmount = (this.config.stakePct / 100) * input.state.bankroll;

      // Calculate shares
      const shares = Math.max(1, Math.floor(stakeAmount / askPrice));

      // DEV mode: Use market orders for natural fills (DEV_FORCE_TRADES=true)
      const devForceTrades = process.env.DEV_FORCE_TRADES === 'true';
      const useMarketOrder = devForceTrades;

      // Create order intent
      const intent: OrderIntent = {
        marketId: market.id,
        side: 'BUY',
        outcome: 'YES',
        shares,
        limitPrice: useMarketOrder ? undefined : askPrice, // Market order if DEV_FORCE_TRADES
        reason: useMarketOrder
          ? `Market order (DEV mode): Edge ${edgePct.toFixed(2)}% (model: ${(pModel * 100).toFixed(1)}%, market: ${(pMarket * 100).toFixed(1)}%)`
          : `Edge detected: ${edgePct.toFixed(2)}% (model: ${(pModel * 100).toFixed(1)}%, market: ${(pMarket * 100).toFixed(1)}%)`,
        modelProb: pModel * 100,
        marketProb: pMarket * 100,
        edgePct,
        stakePct: this.config.stakePct,
      };

      intents.push(intent);
    }

    return intents;
  }
}

