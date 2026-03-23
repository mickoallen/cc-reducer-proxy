"""Deduplicate repeated tool results — keep only the most recent per unique call."""

from typing import Optional, Dict, List, Tuple

# Tools that can be deduplicated and their key-building functions
DEDUP_TOOLS = {"Read", "Bash", "Grep", "Glob"}


def _dedup_key(tool_name: str, input_block: dict) -> Optional[str]:
    """Build a dedup key for a tool_use input. Returns None if not dedupable."""
    if tool_name == "Read":
        file_path = input_block.get("file_path", "")
        if not file_path:
            return None
        offset = input_block.get("offset")
        limit = input_block.get("limit")
        if offset is not None or limit is not None:
            return f"Read:{file_path}:{offset}:{limit}"
        return f"Read:{file_path}"
    elif tool_name == "Bash":
        command = input_block.get("command", "")
        if not command:
            return None
        return f"Bash:{command}"
    elif tool_name == "Grep":
        pattern = input_block.get("pattern", "")
        if not pattern:
            return None
        path = input_block.get("path", "")
        glob = input_block.get("glob", "")
        return f"Grep:{pattern}:{path}:{glob}"
    elif tool_name == "Glob":
        pattern = input_block.get("pattern", "")
        if not pattern:
            return None
        path = input_block.get("path", "")
        return f"Glob:{pattern}:{path}"
    return None


def _dedup_label(tool_name: str, input_block: dict) -> str:
    """Human-readable label for the dedup stub message."""
    if tool_name == "Read":
        return f"Read of {input_block.get('file_path', '?')}"
    elif tool_name == "Bash":
        cmd = input_block.get("command", "?")
        return f"Bash: {cmd[:80]}"
    elif tool_name == "Grep":
        return f"Grep for {input_block.get('pattern', '?')}"
    elif tool_name == "Glob":
        return f"Glob {input_block.get('pattern', '?')}"
    return tool_name


def deduplicate_tool_results(messages: List[dict]) -> Tuple[List[dict], int]:
    """
    Scan tool_result messages for dedupable tool calls (Read, Bash, Grep, Glob).
    When the same call was made multiple times with identical params,
    blank out all but the most recent result.
    Returns (mutated_messages, count_deduplicated).
    """
    # First pass: build tool_use_id -> (dedup_key, label) for dedupable tools
    tool_use_ids: Dict[str, Tuple[str, str]] = {}  # id -> (dedup_key, label)
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if (isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("name") in DEDUP_TOOLS):
                tool_use_id = block.get("id", "")
                tool_name = block.get("name", "")
                input_block = block.get("input", {})
                key = _dedup_key(tool_name, input_block)
                if tool_use_id and key:
                    label = _dedup_label(tool_name, input_block)
                    tool_use_ids[tool_use_id] = (key, label)

    if not tool_use_ids:
        return messages, 0

    # Second pass: find all tool_result blocks for dedupable calls
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
            entry = tool_use_ids.get(tool_use_id)
            if entry:
                key, label = entry
                key_result_locations.setdefault(key, []).append((msg_idx, block_idx, label))

    # Third pass: for keys with multiple results, blank all but the last
    dedup_count = 0
    messages = [dict(m) for m in messages]  # shallow copy top level
    for key, locations in key_result_locations.items():
        if len(locations) <= 1:
            continue
        for msg_idx, block_idx, label in locations[:-1]:
            msg = messages[msg_idx]
            content = list(msg.get("content", []))
            block = dict(content[block_idx])
            block["content"] = f"[deduplicated — superseded by later {label}]"
            content[block_idx] = block
            messages[msg_idx] = dict(msg)
            messages[msg_idx]["content"] = content
            dedup_count += 1

    return messages, dedup_count
