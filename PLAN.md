# Plan: Claude Code API Proxy for Token Reduction

## Context

The hook-based approach (cc-token-reducer) only compresses tool output once — at the moment it arrives. That output then sits in the conversation history for every subsequent LLM call, accumulating forever. A proxy intercepts every API request, so it can compress the full message history on each call. This compounds savings across the whole session rather than just at the moment of first ingestion.

---

## How it works

Claude Code respects the `ANTHROPIC_BASE_URL` environment variable. Point it at a local server and all API traffic routes through it:

```
Claude Code → http://localhost:9099 → api.anthropic.com
```

The proxy sits in that gap, compresses the messages array, then forwards to the real API and streams the response back.

---

## What the proxy can compress (that hooks cannot)

1. **Historical tool results** — a `Read` of a 500-line file from 10 turns ago is still in full in the messages array. Proxy can re-compress or truncate it.
2. **Duplicate tool calls** — if the same file was Read 3 times, keep only the latest result.
3. **Old Bash output** — large stdout from earlier turns can be aggressively trimmed once Claude has already acted on it.
4. **Stale tool results past a TTL** — tool results older than N turns replaced with `[result from N turns ago — truncated]`.

---

## Architecture

### Stack
- **Python**
- **FastAPI + httpx** — async, handles SSE streaming cleanly
- **uvicorn** — ASGI server

### Endpoints
- `POST /v1/messages` — main intercept point
- Pass-through for everything else (`GET /v1/models`, etc.)

### Request flow
1. Receive request from Claude Code
2. Parse `messages` array
3. Apply compression pipeline to message history
4. Forward mutated request to `api.anthropic.com` with real API key
5. Stream SSE response back to Claude Code unchanged

### Compression pipeline (applied per-request)
- **Re-compress tool results** using same rules as cc-token-reducer hooks (ANSI, progress bars, blank lines, license headers, etc.)
- **Truncate stale tool results** — tool_result messages older than configurable TTL (e.g. 10 turns) get trimmed to first N lines + `[truncated — N chars]`
- **Deduplicate file reads** — multiple Read results for same file_path: keep only the most recent
- **Cap tool result size** — hard cap per tool result (e.g. 4000 chars), truncate with notice

---

## Project structure

```
cc-reducer-proxy/
├── proxy.py              # FastAPI app, main entry point
├── compression.py        # Message history compression pipeline
├── rules/
│   ├── tool_results.py   # Re-compress tool output (port from cc-token-reducer)
│   ├── deduplication.py  # Remove duplicate file reads
│   └── truncation.py     # Stale result truncation
├── stats.py              # Per-request stats logging
├── report.py             # CLI stats reporter
├── run.sh                # Start proxy + export ANTHROPIC_BASE_URL
├── requirements.txt
└── README.md
```

---

## Setup UX (target)

```bash
pip install -r requirements.txt

# Option A: script handles env var
./run.sh

# Option B: manual
export ANTHROPIC_BASE_URL=http://localhost:9099
uvicorn proxy:app --port 9099
```

---

## Stats tracking

Per-request JSONL log:
```json
{
  "ts": "...",
  "original_tokens_est": 12400,
  "compressed_tokens_est": 9100,
  "saved": 3300,
  "rules": ["stale_truncation:3", "dedup_read:1", "tool_recompress:8"]
}
```

Report: `python report.py [today|week|all]`

---

## Key implementation notes

- **Streaming is required** — Claude Code uses SSE. Use `httpx.AsyncClient` with `stream=True` and forward chunks as-is.
- **Auth** — proxy reads `ANTHROPIC_API_KEY` from env, strips it from incoming request, injects on outgoing.
- **Start with tool_result compression only** — don't touch assistant/user messages initially. Safe, high value, low risk of degrading quality.
- **Port compression logic** from `cc-token-reducer/hooks/compress-output.py` — `compress_read_output`, `compress_grep_output`, `compress` functions.

---

## Verification

1. `uvicorn proxy:app --port 9099`
2. `export ANTHROPIC_BASE_URL=http://localhost:9099`
3. Start a Claude Code session, do a few Read/Bash/Grep calls
4. Confirm proxy logs show requests flowing through
5. `python report.py today` — verify token savings logged
6. Confirm Claude Code behaviour is identical (no broken responses, no missing tool results)
