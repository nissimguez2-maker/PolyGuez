"""
Helper script to print out and verify common configuration paths used
by the agents project.
"""

from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
  root = Path(__file__).resolve().parents[2]

  config_dir = root / "config"
  logs_dir = root / "logs"

  print(f"Project root: {root}")
  print(f"Config dir: {config_dir} ({'exists' if config_dir.exists() else 'missing'})")
  print(f"Logs dir: {logs_dir} ({'exists' if logs_dir.exists() else 'missing'})")

  env = os.getenv("POLYMARKET_ENV", "not set")
  print(f"POLYMARKET_ENV: {env}")


if __name__ == "__main__":
  main()
