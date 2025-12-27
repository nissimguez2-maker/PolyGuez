# Scripts

This directory contains utility scripts for the Polymarket Agents project.

## fetch_polymarket_samples.ts

Fetches real Polymarket JSON data from Gamma and CLOB APIs and saves raw JSON files to `/samples/` directory.

### What it does

1. Fetches 1-3 markets from Gamma `/markets` endpoint
2. Identifies a binary YES/NO market from the response
3. Extracts `yesTokenId` and `noTokenId` from the market's `clobTokenIds` field
4. Fetches CLOB price and order book data for both tokens
5. Saves raw JSON to:
   - `/samples/gamma_markets.json`
   - `/samples/clob_price_yes.json`
   - `/samples/clob_price_no.json`
   - `/samples/clob_book_yes.json`
   - `/samples/clob_book_no.json`

### Features

- **Retry logic**: 2-3 retries with exponential backoff for all API calls
- **Error handling**: Clear console logs when fields are missing or tokenId not found
- **No hardcoded values**: Dynamically identifies token IDs from API response
- **Robust endpoint discovery**: Tries multiple CLOB API endpoint patterns

### Requirements

- Node.js >= 18.0.0 (for native `fetch` support)
- pnpm >= 8.0.0

### How to run

From the project root:

```bash
pnpm tsx scripts/fetch_polymarket_samples.ts
```

Or using Node directly (if tsx is not available):

```bash
node --loader ts-node/esm scripts/fetch_polymarket_samples.ts
```

Or compile and run:

```bash
pnpm tsc scripts/fetch_polymarket_samples.ts --outDir dist --module esnext --target es2022
node dist/fetch_polymarket_samples.js
```

### Expected output

The script will:
1. Fetch markets from Gamma API
2. Find a binary YES/NO market
3. Extract token IDs
4. Fetch CLOB price and book data
5. Save all files to `/samples/`

Console output will show progress and any warnings/errors.

### Troubleshooting

**If Gamma API returns empty list:**
- The script will exit with an error message
- Check your internet connection and try again

**If tokenId not found:**
- The script will log which field is missing
- Check the market structure in `gamma_markets.json`

**If CLOB API endpoints fail:**
- The script tries multiple endpoint patterns
- If all fail, check Polymarket API documentation for current endpoints

### Notes

- This script fetches **real** data from Polymarket APIs (no mocks)
- All JSON is saved as-is (raw API responses)
- The script is designed to be run locally and handles simple errors gracefully
- **CLOB Price API**: Currently requires authentication. The script uses `outcomePrices` from Gamma API as a fallback (still real data)
- **CLOB Book API**: Works via `/book?token_id={tokenId}` endpoint

### API Endpoints Used

- **Gamma Markets**: `https://gamma-api.polymarket.com/markets`
- **CLOB Book**: `https://clob.polymarket.com/book?token_id={tokenId}` ✅
- **CLOB Price**: `https://clob.polymarket.com/price?token_id={tokenId}` ⚠️ (requires auth, uses Gamma fallback)

