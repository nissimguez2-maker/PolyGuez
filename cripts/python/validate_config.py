#!/usr/bin/env python3

"""
Validate important configuration and environment variables used by the agents.
"""

import os
import sys

REQUIRED_VARS = [
    "POLYGON_WALLET_PRIVATE_KEY",
    "OPENAI_API_KEY",
]

OPTIONAL_VARS = [
    "POLYMARKET_API_BASE",
    "TAVILY_API_KEY",
    "NEWSAPI_API_KEY",
]

def main() -> None:
    missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
    if missing:
        print("Missing required variables:", ", ".join(missing))
        sys.exit(1)
    print("Required variables are set.")

    for v in OPTIONAL_VARS:
        if not os.getenv(v):
            print(f"Warning: optional {v} is not set.")

if __name__ == "__main__":
    main()
