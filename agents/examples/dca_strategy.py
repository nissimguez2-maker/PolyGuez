"""
A simple dollar-cost averaging (DCA) strategy example.

Buys a fixed amount of shares in a selected market at regular intervals.
"""

import time
from agents.polymarket.polymarket import Polymarket  # type: ignore

def main() -> None:
    client = Polymarket()
    markets = client.get_all_markets()
    target = min(markets, key=lambda m: m.spread)

    amount_per_purchase = 10
    interval_seconds = 3600  # 1 hour

    print(f"Starting DCA on market {target.ticker}...")
    while True:
        print(f"Buying {amount_per_purchase} shares of {target.ticker}")
        # Replace with client.place_order(...) to execute
        time.sleep(interval_seconds)

if __name__ == "__main__":
    main()
