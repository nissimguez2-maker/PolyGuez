#!/usr/bin/env python3

"""
Download and save your complete order history from the Polymarket API.

Requires API credentials set in environment.
"""

import json
import os
from pathlib import Path
from agents.polymarket.polymarket import Polymarket  # type: ignore

OUTPUT_FILE = Path("data/order_history_download.json")

def main() -> None:
    client = Polymarket()
    orders = client.get_all_orders()  # type: ignore
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump([o.as_dict() for o in orders], f, indent=2)  # type: ignore
    print(f"Downloaded {len(orders)} orders to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
