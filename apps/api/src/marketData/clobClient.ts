/**
 * Client for fetching price and orderbook data from Polymarket CLOB API
 * Uses /samples as source-of-truth for field names
 */

const CLOB_API_URL = 'https://clob.polymarket.com';

export interface ClobPrice {
  price?: string;
  source?: string;
  [key: string]: unknown;
}

export interface ClobBookOrder {
  price: string;
  size: string;
}

export interface ClobBook {
  market?: string;
  asset_id?: string;
  timestamp?: string;
  hash?: string;
  bids: ClobBookOrder[];
  asks: ClobBookOrder[];
  [key: string]: unknown;
}

/**
 * Fetch price for a token ID
 * Note: CLOB price API may require authentication.
 * Returns fallback data structure if API is unavailable.
 */
export async function fetchPrice(tokenId: string): Promise<ClobPrice> {
  // Try the book endpoint first (works without auth)
  // Price can be derived from best bid/ask
  try {
    const book = await fetchBook(tokenId);
    if (book.bids.length > 0 && book.asks.length > 0) {
      const bestBid = parseFloat(book.bids[0].price);
      const bestAsk = parseFloat(book.asks[0].price);
      const midPrice = (bestBid + bestAsk) / 2;
      return {
        price: midPrice.toString(),
        source: 'clob_book_derived',
      };
    }
  } catch (error) {
    // Fall through to try direct price endpoint
  }

  // Try direct price endpoints (may require auth)
  const priceEndpoints = [
    `/book?token_id=${tokenId}`, // Book endpoint works, derive price
    `/price?token_id=${tokenId}`,
    `/prices?token_id=${tokenId}`,
  ];

  for (const endpoint of priceEndpoints) {
    try {
      const response = await fetch(`${CLOB_API_URL}${endpoint}`);
      if (response.ok) {
        const data = (await response.json()) as any;
        // If it's a book response, derive price
        if (data.bids && data.asks) {
          if (data.bids.length > 0 && data.asks.length > 0) {
            const bestBid = parseFloat(data.bids[0].price);
            const bestAsk = parseFloat(data.asks[0].price);
            const midPrice = (bestBid + bestAsk) / 2;
            return {
              price: midPrice.toString(),
              source: 'clob_book_derived',
            };
          }
        }
        return data as ClobPrice;
      }
    } catch (error) {
      // Continue to next endpoint
    }
  }

  // Return fallback structure
  return {
    price: '0',
    source: 'fallback',
  };
}

/**
 * Fetch orderbook for a token ID
 * Uses /book?token_id={tokenId} endpoint (works without auth)
 */
export async function fetchBook(tokenId: string): Promise<ClobBook> {
  const url = `${CLOB_API_URL}/book?token_id=${tokenId}`;
  const response = await fetch(url);

  if (!response.ok) {
    throw new Error(
      `CLOB API error: ${response.status} ${response.statusText}`
    );
  }

  const book = (await response.json()) as ClobBook;
  return book;
}

