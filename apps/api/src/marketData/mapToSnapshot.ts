/**
 * Maps raw Gamma market data and CLOB price/book data to MarketSnapshot
 * Uses /samples as source-of-truth for field names
 */

import { MarketSnapshot, OutcomeQuote } from '@domain';
import type { GammaMarket } from './gammaClient';
import type { ClobPrice, ClobBook } from './clobClient';

/**
 * Parse stringified JSON array from Gamma API
 */
function parseJsonArray<T>(value: string | T[] | undefined): T[] {
  if (!value) {
    return [];
  }
  if (Array.isArray(value)) {
    return value;
  }
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
}

/**
 * Determine market status from Gamma market data
 */
function getMarketStatus(market: GammaMarket): 'open' | 'closed' | 'resolved' | 'suspended' {
  if (market.closed === true) {
    return 'closed';
  }
  if (market.active === false) {
    return 'suspended';
  }
  // Note: "resolved" status would need additional logic based on resolution data
  if (market.active === true && market.closed === false) {
    return 'open';
  }
  return 'closed'; // Default to closed if unclear
}

/**
 * Extract token IDs from Gamma market
 * Returns { yesTokenId, noTokenId } or null if not found
 */
function extractTokenIds(market: GammaMarket): {
  yesTokenId: string;
  noTokenId: string;
} | null {
  const tokenIds = parseJsonArray<string>(market.clobTokenIds);
  const outcomes = parseJsonArray<string>(market.outcomes);

  if (tokenIds.length < 2 || outcomes.length < 2) {
    return null;
  }

  // Find YES and NO indices
  const outcomesLower = outcomes.map((o) => String(o).toLowerCase());
  const yesIndex = outcomesLower.findIndex((o) => o.includes('yes'));
  const noIndex = outcomesLower.findIndex((o) => o.includes('no'));

  if (yesIndex === -1 || noIndex === -1) {
    return null;
  }

  return {
    yesTokenId: String(tokenIds[yesIndex]),
    noTokenId: String(tokenIds[noIndex]),
  };
}

/**
 * Extract best bid/ask from book data
 */
function getBestBidAsk(book: ClobBook | null | undefined): {
  bestBid?: number;
  bestAsk?: number;
} {
  if (!book || !book.bids || !book.asks) {
    return {};
  }

  const bestBid =
    book.bids.length > 0 ? parseFloat(book.bids[0].price) : undefined;
  const bestAsk =
    book.asks.length > 0 ? parseFloat(book.asks[0].price) : undefined;

  return { bestBid, bestAsk };
}

/**
 * Create OutcomeQuote from market data, price, and book
 */
function createOutcomeQuote(
  side: 'YES' | 'NO',
  market: GammaMarket,
  price: ClobPrice | null | undefined,
  book: ClobBook | null | undefined,
  outcomeIndex: number
): OutcomeQuote {
  const outcomePrices = parseJsonArray<string>(market.outcomePrices);
  const priceValue =
    price?.price && price.price !== '0'
      ? parseFloat(price.price)
      : outcomePrices[outcomeIndex]
        ? parseFloat(outcomePrices[outcomeIndex])
        : 0;

  const { bestBid, bestAsk } = getBestBidAsk(book);

  // Use market-level bestBid/bestAsk if book doesn't have them
  const finalBestBid =
    bestBid !== undefined
      ? bestBid
      : market.bestBid !== undefined
        ? market.bestBid
        : undefined;
  const finalBestAsk =
    bestAsk !== undefined
      ? bestAsk
      : market.bestAsk !== undefined
        ? market.bestAsk
        : undefined;

  const quote: OutcomeQuote = {
    side,
    price: Math.max(0, Math.min(1, priceValue)), // Clamp to [0, 1]
    impliedProb: Math.max(0, Math.min(100, priceValue * 100)), // Convert to percentage
  };

  if (finalBestBid !== undefined) {
    quote.bestBid = Math.max(0, Math.min(1, finalBestBid));
  }
  if (finalBestAsk !== undefined) {
    quote.bestAsk = Math.max(0, Math.min(1, finalBestAsk));
  }
  if (market.lastTradePrice !== undefined) {
    quote.lastTradedPrice = Math.max(0, Math.min(1, market.lastTradePrice));
  }

  return quote;
}

/**
 * Map raw Gamma market and CLOB data to MarketSnapshot
 */
export function mapToSnapshot(
  rawMarket: GammaMarket,
  yesPrice?: ClobPrice | null,
  noPrice?: ClobPrice | null,
  yesBook?: ClobBook | null,
  noBook?: ClobBook | null
): MarketSnapshot | null {
  // Extract token IDs
  const tokenIds = extractTokenIds(rawMarket);
  if (!tokenIds) {
    return null; // Cannot map without token IDs
  }

  // Extract outcomes to determine YES/NO indices
  const outcomes = parseJsonArray<string>(rawMarket.outcomes);
  const outcomesLower = outcomes.map((o) => String(o).toLowerCase());
  const yesIndex = outcomesLower.findIndex((o) => o.includes('yes'));
  const noIndex = outcomesLower.findIndex((o) => o.includes('no'));

  if (yesIndex === -1 || noIndex === -1) {
    return null; // Not a binary YES/NO market
  }

  // Create outcome quotes
  const yesQuote = createOutcomeQuote('YES', rawMarket, yesPrice, yesBook, yesIndex);
  const noQuote = createOutcomeQuote('NO', rawMarket, noPrice, noBook, noIndex);

  // Build snapshot
  const snapshot: MarketSnapshot = {
    id: `market-${rawMarket.id}`, // Internal ID
    externalId: rawMarket.id, // External ID from Gamma API
    title: rawMarket.question || 'Untitled Market',
    status: getMarketStatus(rawMarket),
    yesTokenId: tokenIds.yesTokenId,
    noTokenId: tokenIds.noTokenId,
    yes: yesQuote,
    no: noQuote,
    lastUpdated: rawMarket.updatedAt || new Date().toISOString(),
  };

  // Optional fields
  if (rawMarket.category) {
    snapshot.category = rawMarket.category;
  }
  if (rawMarket.endDate) {
    snapshot.resolvesAt = rawMarket.endDate;
  }

  return snapshot;
}

