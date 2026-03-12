# cc-reducer-proxy

A local proxy that intercepts Claude Code API traffic and compresses the message history on every request — compounding token savings across the full session.

Unlike hook-based approaches that only compress output once at ingestion, the proxy re-applies compression on every API call, so old bloated tool results stay small for the lifetime of the session.

## How it works

```
Claude Code → http://localhost:9099 → api.anthropic.com
```

Claude Code respects the `ANTHROPIC_BASE_URL` environment variable. Point it at the proxy and all traffic routes through it. The proxy compresses the `messages` array before forwarding each request, then streams the response back unchanged.

### Compression pipeline

1. **Re-compress tool results** — strips ANSI codes, progress bars, blank lines, license headers from historical Read/Bash/Grep output
2. **Deduplicate file reads** — if the same file was Read multiple times, only the most recent result is kept in full
3. **Truncate stale results** — tool results older than 10 assistant turns are trimmed to 500 chars
4. **Hard cap** — no single tool result exceeds 4000 chars

## Setup

```bash
pip3 install -r requirements.txt
```

## Usage

```bash
./run.sh
```

This starts the proxy on port 9099. In any shell where you want to use it:

```bash
export ANTHROPIC_BASE_URL=http://localhost:9099
```

Then start Claude Code as normal. The proxy runs transparently — Claude Code behaviour is identical.

To use a different port:

```bash
PORT=8080 ./run.sh
```

## Stats

Savings are logged to `~/.claude/proxy-stats.jsonl` on every request where something was compressed.

```bash
python3 report.py today   # today's savings
python3 report.py week    # last 7 days
python3 report.py all     # all time
```

Example output:

```
=== Today ===
Requests:        42
Chars saved:     284,301  (18.3% reduction)
Tokens saved ~:  71,075

  recompress:    138
  dedup_read:    23
  stale_trunc:   61
  capped:        12
```
