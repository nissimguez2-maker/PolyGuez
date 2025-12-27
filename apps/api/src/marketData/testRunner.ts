/**
 * Test runner to validate market data mapping
 * Maps 1 market and logs snapshot, validates with zod
 */

import { MarketSnapshotSchema } from '../../../../packages/domain/src/validation';
import { MarketDataService } from './MarketDataService';

async function runTest() {
  console.log('🧪 Testing Market Data Service...\n');

  const service = new MarketDataService({
    maxMarkets: 1,
    fetchOrderBooks: true,
    fetchPrices: true,
  });

  try {
    // Fetch market snapshots
    console.log('📊 Fetching market snapshots...');
    const snapshots = await service.getAllMarketSnapshots();

    if (snapshots.length === 0) {
      console.error('❌ No market snapshots found');
      process.exit(1);
    }

    const snapshot = snapshots[0];
    console.log('\n✅ Market Snapshot:');
    console.log(JSON.stringify(snapshot, null, 2));

    // Validate with zod
    console.log('\n🔍 Validating with Zod schema...');
    const validated = MarketSnapshotSchema.parse(snapshot);
    console.log('✅ Validation passed!');

    // Verify token IDs exist
    console.log('\n🔑 Token IDs:');
    console.log(`  YES Token ID: ${validated.yesTokenId}`);
    console.log(`  NO Token ID: ${validated.noTokenId}`);

    if (!validated.yesTokenId || !validated.noTokenId) {
      console.error('❌ Token IDs missing!');
      process.exit(1);
    }

    // Verify outcome quotes
    console.log('\n💰 Outcome Quotes:');
    console.log(`  YES: price=${validated.yes.price}, prob=${validated.yes.impliedProb}%`);
    console.log(`  NO: price=${validated.no.price}, prob=${validated.no.impliedProb}%`);

    if (validated.yes.bestBid !== undefined) {
      console.log(`  YES bestBid: ${validated.yes.bestBid}`);
    }
    if (validated.yes.bestAsk !== undefined) {
      console.log(`  YES bestAsk: ${validated.yes.bestAsk}`);
    }
    if (validated.no.bestBid !== undefined) {
      console.log(`  NO bestBid: ${validated.no.bestBid}`);
    }
    if (validated.no.bestAsk !== undefined) {
      console.log(`  NO bestAsk: ${validated.no.bestAsk}`);
    }

    console.log('\n✅ All checks passed!');
  } catch (error) {
    console.error('❌ Test failed:', error);
    if (error instanceof Error) {
      console.error('Error details:', error.message);
    }
    process.exit(1);
  }
}

// Run test
runTest();

