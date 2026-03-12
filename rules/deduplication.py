"""Deduplicate repeated file Read results — keep only the most recent per file_path."""

from typing import Optional, Dict, List, Tuple


def _read_dedup_key(input_block: dict) -> Optional[str]:
    """Build a dedup key for a Read tool_use input. Returns None if not dedupable."""
    file_path = input_block.get("file_path", "")
    if not file_path:
        return None
    # Only dedup full-file reads (no offset/limit), or reads with identical params
    offset = input_block.get("offset")
    limit = input_block.get("limit")
    if offset is not None or limit is not None:
        return f"{file_path}:{offset}:{limit}"
    return file_path


def deduplicate_reads(messages: List[dict]) -> Tuple[List[dict], int]:
    """
    Scan tool_result messages for Read tool calls.
    When the same file_path was Read multiple times with the same params,
    blank out all but the most recent result.
    Returns (mutated_messages, count_deduplicated).
    """
    # First pass: build tool_use_id -> dedup_key for Read calls
    read_tool_use_ids: Dict[str, Tuple[str, str]] = {}  # id -> (dedup_key, file_path)
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if (isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("name") == "Read"):
                tool_use_id = block.get("id", "")
                input_block = block.get("input", {})
                dedup_key = _read_dedup_key(input_block)
                file_path = input_block.get("file_path", "")
                if tool_use_id and dedup_key:
                    read_tool_use_ids[tool_use_id] = (dedup_key, file_path)

    if not read_tool_use_ids:
        return messages, 0

    # Second pass: find all tool_result blocks that correspond to Read calls
    # Structure: dedup_key -> list of (msg_idx, block_idx, file_path)
    key_result_locations: Dict[str, List[Tuple[int, int, str]]] = {}
    for msg_idx, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block_idx, block in enumerate(content):
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tool_use_id = block.get("tool_use_id", "")
            entry = read_tool_use_ids.get(tool_use_id)
            if entry:
                dedup_key, file_path = entry
                key_result_locations.setdefault(dedup_key, []).append((msg_idx, block_idx, file_path))

    # Third pass: for keys with multiple results, blank all but the last
    dedup_count = 0
    messages = [dict(m) for m in messages]  # shallow copy top level
    for dedup_key, locations in key_result_locations.items():
        if len(locations) <= 1:
            continue
        for msg_idx, block_idx, file_path in locations[:-1]:
            msg = messages[msg_idx]
            content = list(msg.get("content", []))
            block = dict(content[block_idx])
            block["content"] = f"[deduplicated — superseded by later Read of {file_path}]"
            content[block_idx] = block
            messages[msg_idx] = dict(msg)
            messages[msg_idx]["content"] = content
            dedup_count += 1

    return messages, dedup_count
