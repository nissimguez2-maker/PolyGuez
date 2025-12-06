#!/bin/bash
set -euo pipefail

IMAGE_NAME="polymarket-agents:latest"
PROJECT_ROOT="$(pwd)"

docker run --rm -it -v "$PROJECT_ROOT":/home "$IMAGE_NAME" bash
