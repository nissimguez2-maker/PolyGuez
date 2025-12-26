# Market Data Layer

Implementation of market data fetching and mapping from Polymarket APIs to `MarketSnapshot`.

## Files Created

1. **gammaClient.ts** - Fetches raw market data from Gamma API
2. **clobClient.ts** - Fetches price and orderbook data from CLOB API
3. **mapToSnapshot.ts** - Maps raw data to `MarketSnapshot` format
4. **MarketDataService.ts** - Orchestrates fetching and mapping
5. **testRunner.ts** - Test/validation runner

## Field Mapping (from /samples)

### Gamma Market Fields Used:
- `id` → `externalId` (and used for internal `id`)
- `question` → `title`
- `category` → `category` (optional)
- `endDate` → `resolvesAt` (optional)
- `active`, `closed` → `status` (mapped to 'open'|'closed'|'resolved'|'suspended')
- `outcomes` → parsed to find YES/NO indices
- `outcomePrices` → parsed to get price values
- `clobTokenIds` → parsed to extract `yesTokenId` and `noTokenId`
- `bestBid`, `bestAsk` → used as fallback for outcome quotes
- `lastTradePrice` → `lastTradedPrice` in quotes
- `updatedAt` → `lastUpdated`

### CLOB Book Fields Used:
- `bids[0].price` → `bestBid` in outcome quote
- `asks[0].price` → `bestAsk` in outcome quote

### CLOB Price Fields Used:
- `price` → outcome quote price (fallback if book unavailable)

## Verification Questions

### 1. What if bestAsk/bestBid is missing?
**Answer:** In `mapToSnapshot.ts`, `createOutcomeQuote()` function (lines 100-140):
- First tries to get from `book` data (bids/asks arrays)
- Falls back to market-level `bestBid`/`bestAsk` if book unavailable
- Both fields are optional in `OutcomeQuote`, so snapshot is still valid

### 2. What if tokenId doesn't exist?
**Answer:** In `mapToSnapshot.ts`, `extractTokenIds()` function (lines 60-80):
- Returns `null` if `clobTokenIds` has less than 2 tokens
- `mapToSnapshot()` returns `null` if token IDs can't be extracted
- `MarketDataService` filters out null results and continues with next market

### 3. What if outcomes array is not YES/NO?
**Answer:** In `mapToSnapshot.ts`, `mapToSnapshot()` function (lines 145-200):
- Checks if outcomes contain "yes" and "no" (case-insensitive)
- Returns `null` if not a binary YES/NO market
- `MarketDataService.getAllMarketSnapshots()` pre-filters for binary markets

### 4. What if CLOB API calls fail?
**Answer:** In `MarketDataService.ts`, `fetchAndMapMarket()` function (lines 60-100):
- Wraps price/book fetching in try-catch
- Logs warnings but continues without price/book data
- `mapToSnapshot()` uses `outcomePrices` from Gamma as fallback
- Snapshot is still created with available data

### 5. How are prices derived when CLOB price API requires auth?
**Answer:** In `clobClient.ts`, `fetchPrice()` function (lines 25-70):
- First tries to fetch book data (works without auth)
- Derives mid-price from `(bestBid + bestAsk) / 2`
- Falls back to Gamma `outcomePrices` if all CLOB calls fail
- Returns fallback structure with price "0" if everything fails

## How to Verify

### Prerequisites
```bash
# Install dependencies (from project root)
pnpm install

# Build domain package
pnpm -C packages/domain build
```

### Run Test
```bash
# From project root
pnpm -C apps/api test

# Or using tsx directly
cd apps/api
npx tsx src/marketData/testRunner.ts
```

### Expected Output
```
🧪 Testing Market Data Service...

📊 Fetching market snapshots...
✓ Successfully fetched from https://gamma-api.polymarket.com/markets?...
✓ Fetched 20 markets

✅ Market Snapshot:
{
  "id": "market-516710",
  "externalId": "516710",
  "title": "US recession in 2025?",
  "status": "open",
  "yesTokenId": "104173557214744537570424345347209544585775842950109756851652855913015295701992",
  "noTokenId": "44528029102356085806317866371026691780796471200782980570839327755136990994869",
  "yes": {
    "side": "YES",
    "price": 0.0045,
    "impliedProb": 0.45,
    "bestBid": 0.004,
    "bestAsk": 0.005
  },
  "no": {
    "side": "NO",
    "price": 0.9955,
    "impliedProb": 99.55,
    "bestBid": 0.998,
    "bestAsk": 0.999
  },
  "lastUpdated": "2025-12-26T11:29:49.723865Z"
}

🔍 Validating with Zod schema...
✅ Validation passed!

🔑 Token IDs:
  YES Token ID: 104173557214744537570424345347209544585775842950109756851652855913015295701992
  NO Token ID: 44528029102356085806317866371026691780796471200782980570839327755136990994869

💰 Outcome Quotes:
  YES: price=0.0045, prob=0.45%
  NO: price=0.9955, prob=99.55%
  YES bestBid: 0.004
  YES bestAsk: 0.005
  NO bestBid: 0.998
  NO bestAsk: 0.999

✅ All checks passed!
```

### Build Verification
```bash
# Build all packages
pnpm -r build

# Should complete without errors
```

## Rate Limiting

The service is rate-limit aware:
- `MarketDataService` accepts `maxMarkets` config (default: 10)
- `fetchOrderBooks` and `fetchPrices` can be disabled to reduce API calls
- Failed CLOB calls don't block market snapshot creation (uses Gamma fallback)

