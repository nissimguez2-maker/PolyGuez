#!/bin/bash
set -e

REPO_DIR="/repo/PolyGuez"

echo "=== PolyGuez Agent Startup ==="

# Clone or pull the repo
if [ ! -d "$REPO_DIR" ]; then
    echo "Cloning repo..."
    git clone "https://${GITHUB_TOKEN}@github.com/${GITHUB_OWNER}/${GITHUB_REPO}.git" "$REPO_DIR"
else
    echo "Pulling latest..."
    cd "$REPO_DIR" && git pull origin main
fi

# Configure git identity for commits
git config --global user.email "agent@polyguez.bot"
git config --global user.name "PolyGuez Agent"

# Store credentials so git push works
git config --global credential.helper store
echo "https://${GITHUB_TOKEN}@github.com" > ~/.git-credentials

# Install Python deps in the repo
echo "Installing Python deps..."
cd "$REPO_DIR" && pip3 install -r requirements.txt --quiet 2>&1 | tail -3 || true

echo "Starting control panel server..."
cd /app && POLYGUEZ_REPO="$REPO_DIR" node server.js
