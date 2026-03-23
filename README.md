# cc-reducer-proxy

A local proxy that intercepts Claude Code API traffic and compresses the message history on every request — compounding token savings across the full session.

Unlike hook-based approaches that only compress output once at ingestion, the proxy re-applies compression on every API call, so old bloated tool results stay small for the lifetime of the session.

## How it works

```
Claude Code → http://localhost:9099 → api.anthropic.com
```

Claude Code respects the `ANTHROPIC_BASE_URL` environment variable. Point it at the proxy and all traffic routes through it. The proxy compresses the `messages` array before forwarding each request, then streams the response back unchanged.

### Compression pipeline

Applied on every API request, in order:

#### 1. Re-compress tool results

Cleans bloat from Read, Bash, Grep, and Glob tool output:

- **ANSI escape codes** — color/formatting sequences stripped
- **Progress indicators** — percentage bars, spinners (`⠋⠙⠹...`), dot sequences, `[####>---]` bars
- **Blank line collapse** — 3+ consecutive blank lines → 1
- **License headers** — copyright/license comment blocks at the top of files replaced with `[license header - N lines]`
- **Trailing whitespace** — stripped from every line
- **Repetitive lines** (Bash only) — 3+ identical consecutive lines → 1 line + `[repeated N times]`
- **Line truncation** (Bash only) — output capped at 200 lines
- **JSON minification** — JSON output is compacted (whitespace removed)
- **Timestamp prefixes** — ISO timestamps at the start of log lines are stripped when detected in bulk

#### 2. Deduplicate tool results

When the same tool call is made multiple times with identical parameters, only the most recent result is kept. Earlier results are replaced with a stub like `[deduplicated — superseded by later Read of src/foo.py]`.

Applies to: **Read** (same file path + offset/limit), **Bash** (same command), **Grep** (same pattern + path + glob), **Glob** (same pattern + path).

#### 3. Truncate stale results

Tool results older than 10 assistant turns are trimmed to 500 chars, with a `[truncated — result from N turns ago]` notice.

#### 4. Hard cap

Tool results older than 5 assistant turns are capped at 4000 chars.

#### 5. Compress old assistant blocks

For assistant messages older than 10 turns:

- **Text blocks** — Claude's own explanations are truncated to 500 chars. Old prose rarely gets re-referenced.
- **Tool use inputs** — long input values (bash commands, file contents in Write calls) are truncated to 200 chars. The tool name and ID are preserved for result pairing.

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
Requests:        86
Saved:           1,191,475 chars (~397,158 tokens, 29.8% reduction)

  recompress:    5
  dedup_tools:   5
  stale_trunc:   100
  capped:        174
  asst_text:     12
  tool_input:    8
```
