#!/usr/bin/env python3
"""CLI stats reporter: python report.py [today|week|all]"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

STATS_LOG = os.path.expanduser("~/.claude/proxy-stats.jsonl")


def load_entries(since=None):
    if not os.path.exists(STATS_LOG):
        return []
    entries = []
    with open(STATS_LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if since:
                    ts = datetime.fromisoformat(entry["ts"])
                    if ts < since:
                        continue
                entries.append(entry)
            except (json.JSONDecodeError, KeyError):
                continue
    return entries


def summarize(entries: list[dict]):
    if not entries:
        print("No stats found.")
        return

    total_saved_chars = sum(e.get("saved_chars", 0) for e in entries)
    total_saved_tokens = sum(e.get("saved_tokens_est", 0) for e in entries)
    total_original = sum(e.get("original_chars", 0) for e in entries)
    total_requests = len(entries)

    recompress = sum(e.get("rules", {}).get("recompress", 0) for e in entries)
    dedup = sum(e.get("rules", {}).get("dedup_read", 0) for e in entries)
    stale = sum(e.get("rules", {}).get("stale_truncation", 0) for e in entries)
    capped = sum(e.get("rules", {}).get("cap", 0) for e in entries)

    reduction_pct = (total_saved_chars / total_original * 100) if total_original else 0

    print(f"Requests:        {total_requests}")
    print(f"Saved:           {total_saved_chars:,} chars (~{total_saved_tokens:,} tokens, {reduction_pct:.1f}% reduction)")
    print()
    print(f"  recompress:    {recompress}")
    print(f"  dedup_read:    {dedup}")
    print(f"  stale_trunc:   {stale}")
    print(f"  capped:        {capped}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "today"
    now = datetime.now(timezone.utc)

    if mode == "today":
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif mode == "week":
        since = now - timedelta(days=7)
    else:
        since = None

    entries = load_entries(since)
    label = {"today": "Today", "week": "Last 7 days"}.get(mode, "All time")
    print(f"=== {label} ===")
    summarize(entries)


if __name__ == "__main__":
    main()
