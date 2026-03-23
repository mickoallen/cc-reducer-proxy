"""Message history compression pipeline — applied on every proxied request."""

import json
from typing import Any, Dict, List, Tuple

from rules.tool_results import recompress_tool_result
from rules.deduplication import deduplicate_tool_results
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


ASSISTANT_TEXT_STALE_TURNS = 10
ASSISTANT_TEXT_MAX_CHARS = 500
TOOL_INPUT_STALE_TURNS = 10
TOOL_INPUT_MAX_CHARS = 200


def compress_old_assistant_blocks(messages: List[dict]) -> Tuple[List[dict], int, int]:
    """
    Truncate old assistant text blocks and tool_use inputs.
    Returns (messages, text_truncated_count, input_truncated_count).
    """
    total_assistant_turns = sum(1 for m in messages if m.get("role") == "assistant")
    text_truncated = 0
    input_truncated = 0
    result = []
    assistant_turn = 0

    for msg in messages:
        if msg.get("role") != "assistant":
            result.append(msg)
            continue

        assistant_turn += 1
        turns_ago = total_assistant_turns - assistant_turn

        if turns_ago < ASSISTANT_TEXT_STALE_TURNS:
            result.append(msg)
            continue

        content = msg.get("content", [])
        if not isinstance(content, list):
            result.append(msg)
            continue

        new_content = []
        changed = False
        for block in content:
            if not isinstance(block, dict):
                new_content.append(block)
                continue

            if block.get("type") == "text":
                text = block.get("text", "")
                if len(text) > ASSISTANT_TEXT_MAX_CHARS:
                    block = dict(block)
                    block["text"] = text[:ASSISTANT_TEXT_MAX_CHARS] + f"\n[truncated — assistant text from {turns_ago} turns ago]"
                    text_truncated += 1
                    changed = True

            elif block.get("type") == "tool_use":
                inp = block.get("input", {})
                if isinstance(inp, dict):
                    new_inp = {}
                    inp_changed = False
                    for k, v in inp.items():
                        if k in ("id", "name"):
                            new_inp[k] = v
                        elif isinstance(v, str) and len(v) > TOOL_INPUT_MAX_CHARS:
                            new_inp[k] = v[:TOOL_INPUT_MAX_CHARS] + "…[truncated]"
                            inp_changed = True
                        else:
                            new_inp[k] = v
                    if inp_changed:
                        block = dict(block)
                        block["input"] = new_inp
                        input_truncated += 1
                        changed = True

            new_content.append(block)

        if changed:
            msg = dict(msg)
            msg["content"] = new_content
        result.append(msg)

    return result, text_truncated, input_truncated


def compress_messages(messages: List[dict]) -> Tuple[List[dict], dict]:
    """
    Apply the full compression pipeline to the messages array.
    Returns (compressed_messages, stats_dict).
    """
    original_size = _estimate_chars(messages)
    tool_use_map = _get_tool_use_map(messages)

    # 1. Re-compress all tool results
    messages, recompressed = recompress_historical_tool_results(messages, tool_use_map)

    # 2. Deduplicate repeated tool results (Read, Bash, Grep, Glob)
    messages, deduped = deduplicate_tool_results(messages)

    # 3. Truncate stale results
    messages, stale_truncated = truncate_stale_results(messages)

    # 4. Cap oversized results
    messages, capped = cap_tool_results(messages)

    # 5. Compress old assistant text blocks and tool_use inputs
    messages, text_truncated, input_truncated = compress_old_assistant_blocks(messages)

    compressed_size = _estimate_chars(messages)
    saved = original_size - compressed_size

    stats = {
        "original_chars": original_size,
        "compressed_chars": compressed_size,
        "saved_chars": saved,
        "saved_tokens_est": saved // 3,
        "rules": {
            "recompress": recompressed,
            "dedup_tools": deduped,
            "stale_truncation": stale_truncated,
            "cap": capped,
            "assistant_text_truncation": text_truncated,
            "tool_input_truncation": input_truncated,
        },
    }
    return messages, stats


def _estimate_chars(messages: List[dict]) -> int:
    return len(json.dumps(messages))
