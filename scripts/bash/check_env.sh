#!/usr/bin/env bash
set -euo pipefail

# Simple sanity check for the Polymarket Agents .env file.
#
# Usage:
#   ./scripts/bash/check_env.sh
#
# The script checks that the .env file exists and that key variables
# required by the README are present and non-empty.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

REQUIRED_VARS=(
  "POLYGON_WALLET_PRIVATE_KEY"
  "OPENAI_API_KEY"
)

if [ ! -f "${ENV_FILE}" ]; then
  echo "[env-check] .env file not found at: ${ENV_FILE}"
  echo "[env-check] Run: cp .env.example .env and fill in your values."
  exit 1
fi

echo "[env-check] Using env file: ${ENV_FILE}"

missing=0

while IFS='=' read -r key value; do
  case "${key}" in
    ''|\#*)
      continue
      ;;
    *)
      export "${key}=${value}"
      ;;
  esac
done < "${ENV_FILE}"

for var in "${REQUIRED_VARS[@]}"; do
  if [ -z "${!var:-}" ]; then
    echo "[env-check] Missing or empty variable: ${var}"
    missing=1
  fi
done

if [ "${missing}" -ne 0 ]; then
  echo "[env-check] One or more required variables are not set correctly."
  exit 1
fi

echo "[env-check] All required variables are present."
