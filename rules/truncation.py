"""Truncate stale tool results older than TTL turns and cap oversized results."""

from typing import List, Tuple

MAX_RESULT_CHARS = 4000
CAP_TTL_TURNS = 5  # tool results newer than this many assistant turns are never capped
STALE_TTL_TURNS = 10  # tool results older than this many assistant turns get truncated
STALE_MAX_CHARS = 500


def _count_chars(block: dict) -> int:
    content = block.get("content", "")
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(c.get("text", "")) for c in content if isinstance(c, dict))
    return 0


def _truncate_block_content(block: dict, max_chars: int, note: str) -> dict:
    content = block.get("content", "")
    if isinstance(content, str):
        if len(content) <= max_chars:
            return block
        block = dict(block)
        block["content"] = content[:max_chars] + f"\n{note}"
        return block
    if isinstance(content, list):
        full = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
        if len(full) <= max_chars:
            return block
        block = dict(block)
        block["content"] = [{"type": "text", "text": full[:max_chars] + f"\n{note}"}]
        return block
    return block


def cap_tool_results(messages: list) -> Tuple[list, int]:
    """Hard-cap each tool_result at MAX_RESULT_CHARS, skipping recent messages."""
    total_assistant_turns = sum(1 for m in messages if m.get("role") == "assistant")

    capped = 0
    result = []
    assistant_turn = 0

    for msg in messages:
        if msg.get("role") == "assistant":
            assistant_turn += 1
            result.append(msg)
            continue

        if msg.get("role") != "user":
            result.append(msg)
            continue

        content = msg.get("content", [])
        if not isinstance(content, list):
            result.append(msg)
            continue

        turns_ago = total_assistant_turns - assistant_turn
        if turns_ago <= CAP_TTL_TURNS:
            result.append(msg)
            continue

        new_content = []
        changed = False
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                new_block = _truncate_block_content(
                    block, MAX_RESULT_CHARS,
                    f"[capped — result from {turns_ago} turns ago exceeded {MAX_RESULT_CHARS} char limit]"
                )
                if new_block is not block:
                    capped += 1
                    changed = True
                new_content.append(new_block)
            else:
                new_content.append(block)
        if changed:
            msg = dict(msg)
            msg["content"] = new_content
        result.append(msg)
    return result, capped


def truncate_stale_results(messages: list) -> Tuple[list, int]:
    """
    Truncate tool_result blocks that are older than STALE_TTL_TURNS assistant turns.
    'Turns' counted as assistant messages in the history.
    """
    total_assistant_turns = sum(1 for m in messages if m.get("role") == "assistant")

    truncated = 0
    result = []
    assistant_turn = 0

    for msg in messages:
        if msg.get("role") == "assistant":
            assistant_turn += 1
            result.append(msg)
            continue

        if msg.get("role") != "user":
            result.append(msg)
            continue

        content = msg.get("content", [])
        if not isinstance(content, list):
            result.append(msg)
            continue

        turns_ago = total_assistant_turns - assistant_turn
        if turns_ago <= STALE_TTL_TURNS:
            result.append(msg)
            continue

        new_content = []
        changed = False
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                chars = _count_chars(block)
                if chars > STALE_MAX_CHARS:
                    new_block = _truncate_block_content(
                        block, STALE_MAX_CHARS,
                        f"[truncated — result from {turns_ago} turns ago]"
                    )
                    truncated += 1
                    changed = True
                    new_content.append(new_block)
                else:
                    new_content.append(block)
            else:
                new_content.append(block)

        if changed:
            msg = dict(msg)
            msg["content"] = new_content
        result.append(msg)

    return result, truncated
