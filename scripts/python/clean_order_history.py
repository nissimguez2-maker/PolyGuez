#!/usr/bin/env python3

"""
Removes closed orders from the local order history file.
This helps keep JSON history files manageable.
"""

import json
import sys
from pathlib import Path

HISTORY_PATH = Path("data/order_history.json")

def main() -> None:
    if not HISTORY_PATH.exists():
        print(f"No history file found at {HISTORY_PATH}")
        return
    data = json.loads(HISTORY_PATH.read_text())
    original_len = len(data.get("orders", []))
    data["orders"] = [o for o in data.get("orders", []) if o.get("status") != "closed"]
    with open(HISTORY_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Cleaned order history: {original_len} → {len(data['orders'])} active orders")

if __name__ == "__main__":
    main()
