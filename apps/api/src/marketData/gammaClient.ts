/**
 * Client for fetching market data from Polymarket Gamma API
 * Uses /samples as source-of-truth for field names
 */

const GAMMA_API_URL = 'https://gamma-api.polymarket.com';

export interface GammaMarket {
  id: string;
  question?: string;
  category?: string;
  endDate?: string;
  active?: boolean;
  closed?: boolean;
  outcomes?: string; // Stringified JSON array: "[\"Yes\", \"No\"]"
  outcomePrices?: string; // Stringified JSON array: "[\"0.0045\", \"0.9955\"]"
  clobTokenIds?: string; // Stringified JSON array: "[\"token1\", \"token2\"]"
  bestBid?: number;
  bestAsk?: number;
  lastTradePrice?: number;
  updatedAt?: string;
  [key: string]: unknown; // Allow other fields from API
}

/**
 * Fetch markets from Gamma API
 * @param limit Maximum number of markets to fetch
 * @param active Filter for active markets only
 * @param closed Filter for closed markets
 */
export async function fetchMarkets(
  limit: number = 20,
  active: boolean = true,
  closed: boolean = false
): Promise<GammaMarket[]> {
  const params = new URLSearchParams({
    limit: limit.toString(),
    active: active.toString(),
    closed: closed.toString(),
    enableOrderBook: 'true', // Include orderbook data if available
  });

  const url = `${GAMMA_API_URL}/markets?${params.toString()}`;
  const response = await fetch(url);

  if (!response.ok) {
    throw new Error(
      `Gamma API error: ${response.status} ${response.statusText}`
    );
  }

  const markets = (await response.json()) as GammaMarket[];
  return markets;
}

