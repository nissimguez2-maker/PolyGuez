/**
 * Service for fetching and mapping Polymarket market data
 * Orchestrates Gamma and CLOB API calls, then maps to MarketSnapshot
 */

import { MarketSnapshot } from '@domain';
import { fetchMarkets, type GammaMarket } from './gammaClient';
import { fetchPrice, fetchBook, type ClobPrice, type ClobBook } from './clobClient';
import { mapToSnapshot } from './mapToSnapshot';

export interface MarketDataServiceConfig {
  /** Maximum number of markets to fetch and process */
  maxMarkets?: number;
  /** Whether to fetch orderbook data (may be rate-limited) */
  fetchOrderBooks?: boolean;
  /** Whether to fetch price data (may be rate-limited) */
  fetchPrices?: boolean;
}

/**
 * Service for fetching and mapping market data
 */
export class MarketDataService {
  private config: Required<MarketDataServiceConfig>;

  constructor(config: MarketDataServiceConfig = {}) {
    this.config = {
      maxMarkets: config.maxMarkets ?? 10,
      fetchOrderBooks: config.fetchOrderBooks ?? true,
      fetchPrices: config.fetchPrices ?? true,
    };
  }

  /**
   * Fetch all market snapshots
   * Strategy: gamma → select N markets → fetch price/book for tokenIds → map
   */
  async getAllMarketSnapshots(): Promise<MarketSnapshot[]> {
    // 1. Fetch markets from Gamma API
    const markets = await fetchMarkets(
      this.config.maxMarkets * 2, // Fetch more to filter for binary markets
      true, // active
      false // not closed
    );

    // 2. Filter for binary YES/NO markets with token IDs
    const binaryMarkets = markets.filter((market) => {
      const outcomes = this.parseJsonArray<string>(market.outcomes);
      const tokenIds = this.parseJsonArray<string>(market.clobTokenIds);
      return (
        outcomes.length === 2 &&
        tokenIds.length === 2 &&
        outcomes.some((o) => String(o).toLowerCase().includes('yes')) &&
        outcomes.some((o) => String(o).toLowerCase().includes('no'))
      );
    });

    // 3. Limit to maxMarkets
    const selectedMarkets = binaryMarkets.slice(0, this.config.maxMarkets);

    // 4. Fetch price and book data for each market
    const snapshots: MarketSnapshot[] = [];

    for (const market of selectedMarkets) {
      try {
        const snapshot = await this.fetchAndMapMarket(market);
        if (snapshot) {
          snapshots.push(snapshot);
        }
      } catch (error) {
        console.error(`Failed to process market ${market.id}:`, error);
        // Continue with next market
      }
    }

    return snapshots;
  }

  /**
   * Fetch and map a single market
   */
  private async fetchAndMapMarket(
    market: GammaMarket
  ): Promise<MarketSnapshot | null> {
    // Extract token IDs
    const tokenIds = this.parseJsonArray<string>(market.clobTokenIds);
    const outcomes = this.parseJsonArray<string>(market.outcomes);
    const outcomesLower = outcomes.map((o) => String(o).toLowerCase());
    const yesIndex = outcomesLower.findIndex((o) => o.includes('yes'));
    const noIndex = outcomesLower.findIndex((o) => o.includes('no'));

    if (yesIndex === -1 || noIndex === -1 || tokenIds.length < 2) {
      return null;
    }

    const yesTokenId = String(tokenIds[yesIndex]);
    const noTokenId = String(tokenIds[noIndex]);

    // Fetch price and book data (with rate limiting awareness)
    let yesPrice: ClobPrice | null = null;
    let noPrice: ClobPrice | null = null;
    let yesBook: ClobBook | null = null;
    let noBook: ClobBook | null = null;

    try {
      if (this.config.fetchPrices) {
        yesPrice = await fetchPrice(yesTokenId);
        noPrice = await fetchPrice(noTokenId);
      }
    } catch (error) {
      console.warn(`Failed to fetch prices for market ${market.id}:`, error);
      // Continue without prices
    }

    try {
      if (this.config.fetchOrderBooks) {
        yesBook = await fetchBook(yesTokenId);
        noBook = await fetchBook(noTokenId);
      }
    } catch (error) {
      console.warn(`Failed to fetch orderbooks for market ${market.id}:`, error);
      // Continue without orderbooks
    }

    // Map to snapshot
    return mapToSnapshot(market, yesPrice, noPrice, yesBook, noBook);
  }

  /**
   * Helper to parse JSON arrays from Gamma API
   */
  private parseJsonArray<T>(value: string | T[] | undefined): T[] {
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
}

