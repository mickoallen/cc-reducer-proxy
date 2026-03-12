"""Message history compression pipeline — applied on every proxied request."""

import json
from typing import Any, Dict, List, Tuple

from rules.tool_results import recompress_tool_result
from rules.deduplication import deduplicate_reads
from rules.truncation import cap_tool_results, truncate_stale_results


def _get_tool_use_map(messages: List[dict]) -> Dict[str, dict]:
    """Build tool_use_id -> tool_use block map from assistant messages."""
    tool_use_map: Dict[str, dict] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_use_map[block.get("id", "")] = block
    return tool_use_map


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "\n".join(parts)
    return ""


def _set_text(block: dict, text: str) -> dict:
    block = dict(block)
    content = block.get("content", "")
    if isinstance(content, str):
        block["content"] = text
    elif isinstance(content, list):
        block["content"] = [{"type": "text", "text": text}]
    else:
        block["content"] = text
    return block


def recompress_historical_tool_results(
    messages: List[dict],
    tool_use_map: Dict[str, dict],
) -> Tuple[List[dict], int]:
    """Re-run compression rules over all tool_result content."""
    recompressed = 0
    result = []
    for msg in messages:
        if msg.get("role") != "user":
            result.append(msg)
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            result.append(msg)
            continue
        new_content = []
        changed = False
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                new_content.append(block)
                continue
            tool_use_id = block.get("tool_use_id", "")
            tool_use = tool_use_map.get(tool_use_id, {})
            tool_name = tool_use.get("name", "")
            cmd = tool_use.get("input", {}).get("command", "")

            original_text = _extract_text(block.get("content", ""))
            if not original_text.strip():
                new_content.append(block)
                continue

            compressed_text, rules = recompress_tool_result(tool_name, original_text, cmd)

            if compressed_text != original_text:
                block = _set_text(block, compressed_text)
                recompressed += 1
                changed = True

            new_content.append(block)

        if changed:
            msg = dict(msg)
            msg["content"] = new_content
        result.append(msg)
    return result, recompressed


def compress_messages(messages: List[dict]) -> Tuple[List[dict], dict]:
    """
    Apply the full compression pipeline to the messages array.
    Returns (compressed_messages, stats_dict).
    """
    original_size = _estimate_chars(messages)
    tool_use_map = _get_tool_use_map(messages)

    # 1. Re-compress all tool results
    messages, recompressed = recompress_historical_tool_results(messages, tool_use_map)

    # 2. Deduplicate repeated file reads
    messages, deduped = deduplicate_reads(messages)

    # 3. Truncate stale results
    messages, stale_truncated = truncate_stale_results(messages)

    # 4. Cap oversized results
    messages, capped = cap_tool_results(messages)

    compressed_size = _estimate_chars(messages)
    saved = original_size - compressed_size

    stats = {
        "original_chars": original_size,
        "compressed_chars": compressed_size,
        "saved_chars": saved,
        "saved_tokens_est": saved // 4,
        "rules": {
            "recompress": recompressed,
            "dedup_read": deduped,
            "stale_truncation": stale_truncated,
            "cap": capped,
        },
    }
    return messages, stats


def _estimate_chars(messages: List[dict]) -> int:
    return len(json.dumps(messages))
