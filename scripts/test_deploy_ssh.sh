#!/usr/bin/env bash
#
# Simple SSH deploy connection tester.
# Usage:
#   ./scripts/test_deploy_ssh.sh -h host -u user -k /path/to/private_key -p port -t /remote/target
#
set -euo pipefail

usage() {
  echo "Usage: $0 -h HOST -u USER -k KEYFILE [-p PORT] [-t TARGET]"
  echo "  -h HOST    : deploy host (e.g. example.com)"
  echo "  -u USER    : deploy user (e.g. deployuser)"
  echo "  -k KEYFILE : path to private key file"
  echo "  -p PORT    : ssh port (default 22)"
  echo "  -t TARGET  : optional remote target path to scp test"
  exit 1
}

PORT=22
TARGET=""

while getopts "h:u:k:p:t:" opt; do
  case "$opt" in
    h) HOST="$OPTARG" ;;
    u) USER="$OPTARG" ;;
    k) KEY="$OPTARG" ;;
    p) PORT="$OPTARG" ;;
    t) TARGET="$OPTARG" ;;
    *) usage ;;
  esac
done

if [ -z "${HOST:-}" ] || [ -z "${USER:-}" ] || [ -z "${KEY:-}" ]; then
  usage
fi

if [ ! -f "$KEY" ]; then
  echo "Private key file not found: $KEY" >&2
  exit 2
fi

echo "Testing SSH connection to $USER@$HOST:$PORT ..."
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -i "$KEY" -p "$PORT" "$USER@$HOST" "echo OK" || {
  echo "SSH test failed" >&2
  exit 3
}

echo "SSH connection OK."

if [ -n "$TARGET" ]; then
  echo "Testing scp of a small file to $USER@$HOST:$TARGET ..."
  TMPFILE=$(mktemp /tmp/deploy-test.XXXXXX)
  echo "deploy-test" > "$TMPFILE"
  scp -i "$KEY" -P "$PORT" "$TMPFILE" "$USER@$HOST:$TARGET/" && echo "SCP OK" || {
    echo "SCP failed" >&2
    rm -f "$TMPFILE"
    exit 4
  }
  rm -f "$TMPFILE"
fi

echo "All tests passed."

