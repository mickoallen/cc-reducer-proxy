#!/usr/bin/env bash
set -e

# ANTHROPIC_API_KEY is optional — if unset, the client's x-api-key header passes through
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "Note: ANTHROPIC_API_KEY is not set."
  echo "The proxy will pass through the client's auth header (e.g. from Claude Code)."
  echo ""
else
  echo "ANTHROPIC_API_KEY is set — it will override the client's auth header."
  echo ""
fi

# Auto-create venv and install deps if needed
if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
  . venv/bin/activate
  pip install -r requirements.txt
else
  . venv/bin/activate
fi

PORT=${PORT:-9099}

export ANTHROPIC_BASE_URL="http://localhost:$PORT"

echo "Starting cc-reducer-proxy on port $PORT"
echo "ANTHROPIC_BASE_URL=$ANTHROPIC_BASE_URL"
echo ""
echo "Run this in any new shell before starting Claude Code:"
echo "  export ANTHROPIC_BASE_URL=http://localhost:$PORT"
echo ""

exec python3 -m uvicorn proxy:app --port "$PORT" --log-level warning
