#!/usr/bin/env python3
import sys
sys.path.append(".")
from src.market_data.adapter import MarketDataAdapter
from src.market_data.schema import MarketEvent
import time
import asyncio

def main():
    adapter = MarketDataAdapter(provider=None)
    ev = MarketEvent(ts=time.time(), type='book', token_id='TEST_TOKEN', best_bid=0.01, best_ask=0.02, spread_pct=0.01, data={'bids':[{'price':0.01,'size':100}], 'asks':[{'price':0.02,'size':50}], 'timestamp': int(time.time()*1000)})
    adapter._on_provider_event(ev)
    # wait a bit for event handling to run in event loop if scheduled
    import time as _t
    _t.sleep(0.5)
    snap = adapter.get_orderbook('TEST_TOKEN')
    print('snap', bool(snap), getattr(snap, 'best_bid', None))

if __name__ == '__main__':
    main()

