#!/usr/bin/env bash
set -euo pipefail

echo "Running unit tests..."
pytest

if command -v ruff >/dev/null 2>&1; then
  echo "Running ruff..."
  ruff check .
else
  echo "ruff is not installed, skipping lint step."
fi
