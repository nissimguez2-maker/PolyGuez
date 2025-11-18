#!/usr/bin/env bash

# Helper script to activate the uv-managed Python 3.12 environment and
# ensure the repository root is on PYTHONPATH.

set -euo pipefail

UV_ENV_DIR="$(pwd)/polymarket-3.12"
if [[ ! -d "$UV_ENV_DIR" ]]; then
  echo "uv environment not found at $UV_ENV_DIR"
  echo "Create it with: uv venv polymarket-3.12 --python python3.12"
  exit 1
fi

# shellcheck source=/dev/null
source "$UV_ENV_DIR/bin/activate"
export PYTHONPATH="$(pwd)"
echo "Activated polymarket-3.12 (Python $(python --version 2>&1))"
echo "PYTHONPATH set to $(pwd)"
