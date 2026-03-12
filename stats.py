"""Per-request stats logging."""

import json
import os
from datetime import datetime, timezone

STATS_LOG = os.path.expanduser("~/.claude/proxy-stats.jsonl")


def log_request(model: str, stats: dict):
    os.makedirs(os.path.dirname(STATS_LOG), exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": model,
        **stats,
    }
    with open(STATS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
