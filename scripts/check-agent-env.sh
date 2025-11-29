#!/usr/bin/env bash
set -euo pipefail

echo "=== Polymarket Agents environment check ==="
echo

# 1. Python version
echo "[1/4] Checking Python version (expected: 3.9)..."
if command -v python3 >/dev/null 2>&1; then
  PYTHON_VERSION_RAW="$(python3 --version 2>&1 || true)"
  echo "Detected: ${PYTHON_VERSION_RAW}"
else
  echo "python3 is not on PATH. Please install Python 3.9 and try again."
fi
echo

# 2. Virtual environment and requirements.txt
echo "[2/4] Checking virtual environment and requirements.txt..."
if [ -d ".venv" ]; then
  echo "Virtual environment directory .venv detected."
else
  echo "No .venv directory found. You may want to create one with:"
  echo "  python3 -m venv .venv"
fi

if [ -f "requirements.txt" ]; then
  echo "requirements.txt found."
else
  echo "requirements.txt is missing. Make sure you are in the repository root."
fi
echo

# 3. .env and required keys
echo "[3/4] Checking .env and required keys..."
if [ -f ".env" ]; then
  echo ".env file found."
else
  echo ".env file not found. You can create one from .env.example:"
  echo "  cp .env.example .env"
fi

check_env_var() {
  local var_name="$1"
  if [ -f ".env" ]; then
    if grep -E "^${var_name}=" ".env" >/dev/null 2>&1; then
      local value
      value="$(grep -E "^${var_name}=" ".env" | head -n 1 | cut -d'=' -f2-)"
      if [ -n "${value}" ]; then
        echo "  ${var_name} is set (value hidden)."
      else
        echo "  ${var_name} is present but empty."
      fi
    else
      echo "  ${var_name} is not present in .env."
    fi
  else
    echo "  ${var_name} cannot be checked because .env is missing."
  fi
}

echo "Checking key variables:"
check_env_var "POLYGON_WALLET_PRIVATE_KEY"
check_env_var "OPENAI_API_KEY"
echo

# 4. Basic CLI availability
echo "[4/4] Checking CLI entrypoint..."
if [ -f "scripts/python/cli.py" ]; then
  echo "CLI script scripts/python/cli.py found."
  echo "You should be able to run:"
  echo "  python scripts/python/cli.py --help"
else
  echo "scripts/python/cli.py not found. Make sure you are on the main branch of this repository."
fi

echo
echo "Environment check complete."
echo "Fix any missing tools or configuration before running CLI commands"
echo "or starting agents against the Polymarket API."
