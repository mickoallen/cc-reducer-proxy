#!/usr/bin/env bash
set -e

PORT=${PORT:-9099}

export ANTHROPIC_BASE_URL="http://localhost:$PORT"

echo "Starting cc-reducer-proxy on port $PORT"
echo "ANTHROPIC_BASE_URL=$ANTHROPIC_BASE_URL"
echo ""
echo "Run this in any new shell before starting Claude Code:"
echo "  export ANTHROPIC_BASE_URL=http://localhost:$PORT"
echo ""

exec python3 -m uvicorn proxy:app --port "$PORT" --log-level info
