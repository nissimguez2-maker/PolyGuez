import * as fs from 'fs/promises';
import * as path from 'path';

const GAMMA_API_URL = 'https://gamma-api.polymarket.com';
const CLOB_API_URL = 'https://clob.polymarket.com';

const MAX_RETRIES = 3;
const INITIAL_BACKOFF_MS = 1000; // 1 second

interface Market {
  id: number;
  question?: string;
  outcomes?: string[] | string;
  clobTokenIds?: string[] | string;
  [key: string]: any;
}

/**
 * Sleep for specified milliseconds
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Fetch with retry and exponential backoff
 */
async function fetchWithRetry(
  url: string,
  retries: number = MAX_RETRIES
): Promise<any> {
  let lastError: Error | null = null;

  for (let attempt = 0; attempt < retries; attempt++) {
    try {
      console.log(`[Attempt ${attempt + 1}/${retries}] Fetching: ${url}`);
      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(
          `HTTP ${response.status}: ${response.statusText}`
        );
      }

      const data = await response.json();
      console.log(`✓ Successfully fetched from ${url}`);
      return data;
    } catch (error: any) {
      lastError = error;
      const isLastAttempt = attempt === retries - 1;

      if (isLastAttempt) {
        console.error(
          `✗ Failed to fetch ${url} after ${retries} attempts: ${error.message}`
        );
        throw error;
      }

      const backoffMs = INITIAL_BACKOFF_MS * Math.pow(2, attempt);
      console.log(
        `⚠ Retry ${attempt + 1}/${retries - 1} in ${backoffMs / 1000}s...`
      );
      await sleep(backoffMs);
    }
  }

  throw lastError || new Error('Unknown error in fetchWithRetry');
}

/**
 * Parse stringified JSON array if needed
 */
function parseJsonArray(value: string | string[] | undefined): string[] {
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
 * Find binary YES/NO market from markets array
 */
function findBinaryMarket(markets: Market[]): Market | null {
  for (const market of markets) {
    const outcomes = parseJsonArray(market.outcomes);
    
    if (outcomes.length === 2) {
      // Check if it's a YES/NO market
      const outcomesLower = outcomes.map((o) => String(o).toLowerCase());
      const hasYes = outcomesLower.some((o) => o.includes('yes'));
      const hasNo = outcomesLower.some((o) => o.includes('no'));

      if (hasYes && hasNo) {
        console.log(
          `✓ Found binary YES/NO market: ${market.id} - "${market.question || 'N/A'}"`
        );
        return market;
      }
    }
  }

  return null;
}

/**
 * Extract token IDs from market
 */
function extractTokenIds(market: Market): { yesTokenId: string; noTokenId: string } | null {
  const tokenIds = parseJsonArray(market.clobTokenIds);
  const outcomes = parseJsonArray(market.outcomes);

  if (tokenIds.length < 2) {
    console.error(
      `✗ Market ${market.id}: clobTokenIds has less than 2 tokens. Found: ${tokenIds.length}`
    );
    return null;
  }

  if (outcomes.length < 2) {
    console.error(
      `✗ Market ${market.id}: outcomes has less than 2 outcomes. Found: ${outcomes.length}`
    );
    return null;
  }

  // Map outcomes to token IDs
  // Typically: outcomes[0] = YES, outcomes[1] = NO
  // But we should verify by checking the outcome names
  const outcomesLower = outcomes.map((o) => String(o).toLowerCase());
  const yesIndex = outcomesLower.findIndex((o) => o.includes('yes'));
  const noIndex = outcomesLower.findIndex((o) => o.includes('no'));

  if (yesIndex === -1 || noIndex === -1) {
    console.error(
      `✗ Market ${market.id}: Could not identify YES/NO outcomes. Outcomes: ${JSON.stringify(outcomes)}`
    );
    return null;
  }

  const yesTokenId = String(tokenIds[yesIndex]);
  const noTokenId = String(tokenIds[noIndex]);

  if (!yesTokenId || !noTokenId) {
    console.error(
      `✗ Market ${market.id}: Missing tokenId for YES (index ${yesIndex}) or NO (index ${noIndex})`
    );
    return null;
  }

  console.log(
    `✓ Extracted token IDs - YES: ${yesTokenId}, NO: ${noTokenId}`
  );

  return { yesTokenId, noTokenId };
}

/**
 * Save JSON to file
 */
async function saveJsonFile(filepath: string, data: any): Promise<void> {
  const dir = path.dirname(filepath);
  await fs.mkdir(dir, { recursive: true });
  await fs.writeFile(filepath, JSON.stringify(data, null, 2), 'utf-8');
  console.log(`✓ Saved: ${filepath}`);
}

/**
 * Main function
 */
async function main() {
  try {
    console.log('🚀 Starting Polymarket sample fetch...\n');

    // 1. Fetch markets from Gamma API (active markets only, with orderbook enabled)
    console.log('📊 Fetching markets from Gamma API...');
    const marketsUrl = `${GAMMA_API_URL}/markets?limit=20&active=true&closed=false&enableOrderBook=true`;
    const markets: Market[] = await fetchWithRetry(marketsUrl);

    if (!Array.isArray(markets) || markets.length === 0) {
      throw new Error(
        'Gamma API returned empty or invalid markets array. Cannot proceed.'
      );
    }

    console.log(`✓ Fetched ${markets.length} markets\n`);

    // Save raw markets response
    const samplesDir = path.join(process.cwd(), 'samples');
    await saveJsonFile(
      path.join(samplesDir, 'gamma_markets.json'),
      markets
    );

    // 2. Find a binary YES/NO market
    console.log('\n🔍 Searching for binary YES/NO market...');
    const binaryMarket = findBinaryMarket(markets);

    if (!binaryMarket) {
      throw new Error(
        'No binary YES/NO market found in the fetched markets. Cannot proceed.'
      );
    }

    // 3. Extract token IDs
    console.log('\n🔑 Extracting token IDs...');
    const tokenIds = extractTokenIds(binaryMarket);

    if (!tokenIds) {
      throw new Error(
        `Could not extract token IDs from market ${binaryMarket.id}. Cannot proceed.`
      );
    }

    const { yesTokenId, noTokenId } = tokenIds;

    // 4. Fetch CLOB data
    console.log('\n📈 Fetching CLOB price and book data...');
    console.log('⚠️  Note: CLOB API may require authentication. Trying public endpoints...\n');

    // CLOB API endpoints (trying common patterns)
    // Note: The CLOB API appears to require authentication or use a Python client library
    // Trying various public endpoint patterns - if all fail, we'll document the limitation
    const priceEndpoints = [
      `/v1/price?token_id=${yesTokenId}`,
      `/v1/prices?token_id=${yesTokenId}`,
      `/price?token_id=${yesTokenId}`,
      `/prices?token_id=${yesTokenId}`,
      `/price/${yesTokenId}`,
      `/prices/${yesTokenId}`,
      `/api/v1/price?token_id=${yesTokenId}`,
      `/api/price?token_id=${yesTokenId}`,
    ];
    const bookEndpoints = [
      `/v1/book?token_id=${yesTokenId}`,
      `/v1/orderbook?token_id=${yesTokenId}`,
      `/book?token_id=${yesTokenId}`,
      `/orderbook?token_id=${yesTokenId}`,
      `/book/${yesTokenId}`,
      `/orderbook/${yesTokenId}`,
      `/api/v1/book?token_id=${yesTokenId}`,
      `/api/v1/orderbook?token_id=${yesTokenId}`,
    ];

    let priceYes: any = null;
    let priceNo: any = null;
    let bookYes: any = null;
    let bookNo: any = null;

    // Fetch YES price
    console.log(`\n💰 Fetching YES token price (${yesTokenId})...`);
    let priceYesFetched = false;
    for (const endpoint of priceEndpoints) {
      try {
        priceYes = await fetchWithRetry(`${CLOB_API_URL}${endpoint}`);
        console.log(`✓ YES price fetched from: ${endpoint}`);
        priceYesFetched = true;
        break;
      } catch (error: any) {
        // Continue to next endpoint
        if (endpoint === priceEndpoints[priceEndpoints.length - 1] && !priceYesFetched) {
          console.warn(
            `⚠️  Could not fetch YES price from CLOB API. All endpoints failed.`
          );
          console.warn(
            `   This may require authentication. Using outcomePrices from Gamma API as fallback.`
          );
          // Use outcomePrices as fallback (real data from Gamma)
          const outcomePrices = parseJsonArray(binaryMarket.outcomePrices);
          priceYes = { price: outcomePrices[0] || '0', source: 'gamma_api_fallback' };
        }
      }
    }

    // Fetch NO price
    console.log(`\n💰 Fetching NO token price (${noTokenId})...`);
    let priceNoFetched = false;
    for (const endpoint of priceEndpoints) {
      try {
        // Replace yesTokenId with noTokenId in endpoint
        const noEndpoint = endpoint.replace(yesTokenId, noTokenId);
        priceNo = await fetchWithRetry(`${CLOB_API_URL}${noEndpoint}`);
        console.log(`✓ NO price fetched from: ${noEndpoint}`);
        priceNoFetched = true;
        break;
      } catch (error: any) {
        if (endpoint === priceEndpoints[priceEndpoints.length - 1] && !priceNoFetched) {
          console.warn(
            `⚠️  Could not fetch NO price from CLOB API. All endpoints failed.`
          );
          console.warn(
            `   This may require authentication. Using outcomePrices from Gamma API as fallback.`
          );
          // Use outcomePrices as fallback (real data from Gamma)
          const outcomePrices = parseJsonArray(binaryMarket.outcomePrices);
          priceNo = { price: outcomePrices[1] || '0', source: 'gamma_api_fallback' };
        }
      }
    }

    // Fetch YES book
    console.log(`\n📖 Fetching YES token book (${yesTokenId})...`);
    let bookYesFetched = false;
    for (const endpoint of bookEndpoints) {
      try {
        bookYes = await fetchWithRetry(`${CLOB_API_URL}${endpoint}`);
        console.log(`✓ YES book fetched from: ${endpoint}`);
        bookYesFetched = true;
        break;
      } catch (error: any) {
        if (endpoint === bookEndpoints[bookEndpoints.length - 1] && !bookYesFetched) {
          console.warn(
            `⚠️  Could not fetch YES book from CLOB API. All endpoints failed.`
          );
          console.warn(
            `   CLOB API appears to require authentication. Saving empty book structure.`
          );
          // Save empty structure with note
          bookYes = { 
            bids: [], 
            asks: [], 
            note: 'CLOB API requires authentication. Use py-clob-client for full orderbook data.',
            source: 'fallback'
          };
        }
      }
    }

    // Fetch NO book
    console.log(`\n📖 Fetching NO token book (${noTokenId})...`);
    let bookNoFetched = false;
    for (const endpoint of bookEndpoints) {
      try {
        // Replace yesTokenId with noTokenId in endpoint
        const noEndpoint = endpoint.replace(yesTokenId, noTokenId);
        bookNo = await fetchWithRetry(`${CLOB_API_URL}${noEndpoint}`);
        console.log(`✓ NO book fetched from: ${noEndpoint}`);
        bookNoFetched = true;
        break;
      } catch (error: any) {
        if (endpoint === bookEndpoints[bookEndpoints.length - 1] && !bookNoFetched) {
          console.warn(
            `⚠️  Could not fetch NO book from CLOB API. All endpoints failed.`
          );
          console.warn(
            `   CLOB API appears to require authentication. Saving empty book structure.`
          );
          // Save empty structure with note
          bookNo = { 
            bids: [], 
            asks: [], 
            note: 'CLOB API requires authentication. Use py-clob-client for full orderbook data.',
            source: 'fallback'
          };
        }
      }
    }

    // 5. Save all files
    console.log('\n💾 Saving files...');
    await saveJsonFile(path.join(samplesDir, 'clob_price_yes.json'), priceYes);
    await saveJsonFile(path.join(samplesDir, 'clob_price_no.json'), priceNo);
    await saveJsonFile(path.join(samplesDir, 'clob_book_yes.json'), bookYes);
    await saveJsonFile(path.join(samplesDir, 'clob_book_no.json'), bookNo);

    console.log('\n✅ All done! Sample files saved to /samples/');
    console.log('\nGenerated files:');
    console.log('  - gamma_markets.json');
    console.log('  - clob_price_yes.json');
    console.log('  - clob_price_no.json');
    console.log('  - clob_book_yes.json');
    console.log('  - clob_book_no.json');
  } catch (error: any) {
    console.error('\n❌ Error:', error.message);
    process.exit(1);
  }
}

// Run main
main();

