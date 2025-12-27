import { AgentState, MarketSnapshot, OrderIntent, Position, OutcomeQuote } from '@domain';
import { TradeFill, ApplyOrderIntentsResult } from './types';

/**
 * Get the quote for a specific outcome from a market snapshot
 */
function getOutcomeQuote(market: MarketSnapshot, outcome: 'YES' | 'NO'): OutcomeQuote {
  return outcome === 'YES' ? market.yes : market.no;
}

/**
 * Get fill price for an order based on market data
 */
function getFillPrice(
  quote: OutcomeQuote,
  side: 'BUY' | 'SELL',
  limitPrice?: number
): number | null {
  // Market order: use best bid/ask, fallback to lastTradedPrice
  if (limitPrice === undefined) {
    if (side === 'BUY') {
      return quote.bestAsk ?? quote.lastTradedPrice ?? null;
    } else {
      return quote.bestBid ?? quote.lastTradedPrice ?? null;
    }
  }

  // Limit order: check if price is acceptable
  if (side === 'BUY') {
    const fillPrice = quote.bestAsk ?? quote.lastTradedPrice;
    if (fillPrice === undefined || fillPrice === null) {
      return null;
    }
    return fillPrice <= limitPrice ? fillPrice : null;
  } else {
    const fillPrice = quote.bestBid ?? quote.lastTradedPrice;
    if (fillPrice === undefined || fillPrice === null) {
      return null;
    }
    return fillPrice >= limitPrice ? fillPrice : null;
  }
}

/**
 * Calculate notional value of a trade (shares * price)
 */
function calculateNotional(shares: number, price: number): number {
  return shares * price;
}

/**
 * Calculate total exposure across all positions
 */
function calculateTotalExposure(positions: Position[], markets: Map<string, MarketSnapshot>): number {
  let totalExposure = 0;
  for (const position of positions) {
    const market = markets.get(position.marketId);
    if (!market) continue;

    const quote = getOutcomeQuote(market, position.outcome);
    const currentPrice = quote.price;
    const notional = calculateNotional(position.shares, currentPrice);
    totalExposure += notional;
  }
  return totalExposure;
}

/**
 * Clip shares based on risk limits
 */
function clipSharesForRisk(
  shares: number,
  price: number,
  bankroll: number,
  maxRiskPerTradePct: number,
  currentExposure: number,
  maxExposurePct: number
): number {
  const notional = calculateNotional(shares, price);
  const maxRiskPerTrade = (maxRiskPerTradePct / 100) * bankroll;
  const maxExposure = (maxExposurePct / 100) * bankroll;

  // Calculate max shares allowed by trade risk
  const maxSharesByTradeRisk = Math.floor(maxRiskPerTrade / price);

  // Calculate max shares allowed by exposure limit
  const availableExposure = Math.max(0, maxExposure - currentExposure);
  const maxSharesByExposure = Math.floor(availableExposure / price);

  // Take the minimum of both limits (most restrictive)
  const clippedShares = Math.min(shares, maxSharesByTradeRisk, maxSharesByExposure);

  return Math.max(0, clippedShares);
}

/**
 * Find existing position for a market/outcome
 */
function findPosition(
  positions: Position[],
  marketId: string,
  outcome: 'YES' | 'NO'
): Position | undefined {
  return positions.find((p) => p.marketId === marketId && p.outcome === outcome);
}

/**
 * Calculate realized PnL when reducing a position
 */
function calculateRealizedPnl(
  sharesReduced: number,
  avgEntryPrice: number,
  exitPrice: number,
  side: 'BUY' | 'SELL'
): number {
  // When reducing a long position (SELL), profit = (exitPrice - entryPrice) * shares
  // This applies to both BUY and SELL orders that reduce a position
  // (In our system, we only support long positions, so SELL always reduces)
  return (exitPrice - avgEntryPrice) * sharesReduced;
}

/**
 * Update position after a fill
 */
function updatePosition(
  position: Position | undefined,
  marketId: string,
  outcome: 'YES' | 'NO',
  side: 'BUY' | 'SELL',
  shares: number,
  price: number
): { position: Position | null; realizedPnl: number } {
  let realizedPnl = 0;

  // If no existing position, create new one
  if (!position) {
    if (side === 'SELL') {
      // Can't sell what we don't have
      return { position: null, realizedPnl: 0 };
    }
    return {
      position: {
        marketId,
        outcome,
        shares,
        avgEntryPrice: price,
        realizedPnl: 0,
        unrealizedPnl: 0,
      },
      realizedPnl: 0,
    };
  }

  // Existing position logic
  if (side === 'BUY') {
    // Adding to position
    const totalShares = position.shares + shares;
    const totalCost = position.shares * position.avgEntryPrice + shares * price;
    const newAvgEntryPrice = totalCost / totalShares;

    return {
      position: {
        ...position,
        shares: totalShares,
        avgEntryPrice: newAvgEntryPrice,
        realizedPnl: position.realizedPnl, // Keep existing realized PnL
      },
      realizedPnl: 0,
    };
  } else {
    // Reducing position (SELL)
    if (position.shares < shares) {
      // Can't sell more than we have
      return { position: null, realizedPnl: 0 };
    }

    const sharesRemaining = position.shares - shares;
    realizedPnl = calculateRealizedPnl(shares, position.avgEntryPrice, price, 'SELL');

    if (sharesRemaining === 0) {
      // Position closed
      return { position: null, realizedPnl };
    }

    return {
      position: {
        ...position,
        shares: sharesRemaining,
        realizedPnl: position.realizedPnl + realizedPnl, // Accumulate realized PnL
        // avgEntryPrice stays the same when reducing
      },
      realizedPnl,
    };
  }
}

/**
 * Calculate unrealized PnL for all positions
 */
function calculateUnrealizedPnl(
  positions: Position[],
  markets: Map<string, MarketSnapshot>
): Map<string, number> {
  const unrealizedMap = new Map<string, number>();

  for (const position of positions) {
    const market = markets.get(position.marketId);
    if (!market) continue;

    const quote = getOutcomeQuote(market, position.outcome);
    const currentPrice = quote.price;
    const unrealized = (currentPrice - position.avgEntryPrice) * position.shares;
    unrealizedMap.set(`${position.marketId}:${position.outcome}`, unrealized);
  }

  return unrealizedMap;
}

/**
 * Apply order intents to agent state and return new state with fills
 */
export function applyOrderIntents(
  state: AgentState,
  markets: MarketSnapshot[],
  intents: OrderIntent[]
): ApplyOrderIntentsResult {
  const marketMap = new Map<string, MarketSnapshot>();
  for (const market of markets) {
    marketMap.set(market.id, market);
  }

  const newPositions: Position[] = [...state.openPositions];
  const fills: TradeFill[] = [];
  const rejected: Array<{ intent: OrderIntent; reason: string }> = [];
  let totalRealizedPnl = 0;
  const timestamp = new Date().toISOString();

  // Process each intent
  for (const intent of intents) {
    // Find market
    const market = marketMap.get(intent.marketId);
    if (!market) {
      rejected.push({ intent, reason: `Market ${intent.marketId} not found` });
      continue;
    }

    // Get quote for outcome
    const quote = getOutcomeQuote(market, intent.outcome);

    // Get fill price
    const fillPrice = getFillPrice(quote, intent.side, intent.limitPrice);
    if (fillPrice === null) {
      rejected.push({
        intent,
        reason: `No fill price available (limit order may not be fillable)`,
      });
      continue;
    }

    // Find existing position (needed for SELL check and exposure calculation)
    const existingPosition = findPosition(newPositions, intent.marketId, intent.outcome);

    // Check if we can sell (have position) - must check before risk clipping
    if (intent.side === 'SELL' && !existingPosition) {
      rejected.push({
        intent,
        reason: `Cannot sell ${intent.outcome} shares without existing position`,
      });
      continue;
    }

    // Calculate current exposure
    const currentExposure = calculateTotalExposure(newPositions, marketMap);

    // Clip shares for risk
    let sharesToFill = clipSharesForRisk(
      intent.shares,
      fillPrice,
      state.bankroll,
      state.maxRiskPerTradePct,
      currentExposure,
      state.maxExposurePct
    );

    if (sharesToFill === 0) {
      rejected.push({
        intent,
        reason: `Risk limits would result in 0 shares`,
      });
      continue;
    }

    // Check if we have enough shares to sell
    if (intent.side === 'SELL' && existingPosition && existingPosition.shares < sharesToFill) {
      sharesToFill = existingPosition.shares;
    }

    // Update position
    const { position: updatedPosition, realizedPnl } = updatePosition(
      existingPosition,
      intent.marketId,
      intent.outcome,
      intent.side,
      sharesToFill,
      fillPrice
    );

    // Update positions array
    if (existingPosition) {
      const index = newPositions.indexOf(existingPosition);
      if (updatedPosition) {
        newPositions[index] = updatedPosition;
      } else {
        newPositions.splice(index, 1);
      }
    } else if (updatedPosition) {
      newPositions.push(updatedPosition);
    }

    totalRealizedPnl += realizedPnl;

    // Create fill
    fills.push({
      agentId: state.agentId,
      marketId: intent.marketId,
      side: intent.side,
      outcome: intent.outcome,
      shares: sharesToFill,
      price: fillPrice,
      timestamp,
      realizedPnlOnFill: realizedPnl,
    });
  }

  // Calculate unrealized PnL for all positions
  const unrealizedMap = calculateUnrealizedPnl(newPositions, marketMap);
  for (let i = 0; i < newPositions.length; i++) {
    const pos = newPositions[i];
    const key = `${pos.marketId}:${pos.outcome}`;
    const unrealized = unrealizedMap.get(key) ?? 0;
    newPositions[i] = {
      ...pos,
      unrealizedPnl: unrealized,
    };
  }

  // Calculate total PnL
  // pnlTotal = realized PnL (from all closed/reduced positions) + unrealized PnL (from open positions)
  const totalUnrealizedPnl = Array.from(unrealizedMap.values()).reduce((sum, val) => sum + val, 0);
  const previousUnrealizedPnl = state.openPositions.reduce((sum, p) => sum + p.unrealizedPnl, 0);
  const pnlTotal = state.pnlTotal + totalRealizedPnl + (totalUnrealizedPnl - previousUnrealizedPnl);

  // Update bankroll (bankroll changes with realized PnL)
  const newBankroll = state.bankroll + totalRealizedPnl;

  // Create new state
  const newState: AgentState = {
    ...state,
    bankroll: Math.max(0, newBankroll),
    pnlTotal,
    openPositions: newPositions,
    timestamp,
  };

  return {
    newState,
    fills,
    rejected,
  };
}

