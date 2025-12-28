#!/usr/bin/env python3

"""
Example utility that notifies when a position's unrealized profit exceeds a threshold.
This script is illustrative only and does not place trades.
"""

import os
import time
from agents.polymarket.polymarket import Polymarket  # type: ignore

THRESHOLD = float(os.getenv("PROFIT_THRESHOLD", "50"))  # in USD
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))  # seconds

def main() -> None:
    client = Polymarket()
    while True:
        positions = client.get_positions()
        for p in positions:
            profit = p.unrealized_pnl
            if profit >= THRESHOLD:
                print(f"🚀 Position {p.ticker} profit {profit:.2f} exceeds threshold {THRESHOLD}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
