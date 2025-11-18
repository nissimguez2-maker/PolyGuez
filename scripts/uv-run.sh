#!/usr/bin/env bash

# Convenience wrapper to run uv within the uv-managed Python 3.12 environment.
# Ensures the uv environment is activated and the repository root is on PYTHONPATH.
set -euo pipefail

ROOT_DIR=$(pwd)
UV_ENV_DIR="${ROOT_DIR%/}/polymarket-3.12"
if [[ ! -d "$UV_ENV_DIR" ]]; then
  echo "[uv-run] uv environment not found at $UV_ENV_DIR" >&2
  echo "Please create it with: uv venv polymarket-3.12 --python 3.12 && source $ROOT_DIR/polymarket-3.12/bin/activate" >&2
  exit 1
fi

# Activate the uv-managed environment
source "$UV_ENV_DIR/bin/activate"
export PYTHONPATH="$ROOT_DIR"

# Forward all arguments to `uv run`
uv run "$@"
