"""Re-compress tool result text — ported from cc-token-reducer hooks/compress-output.py."""

import json
import os
import re
from typing import List, Tuple

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
PROGRESS_LINE = re.compile(
    r"^.*("
    r"\d+%"
    r"|[#=>\-]{5,}"
    r"|\.{4,}"
    r"|⠋|⠙|⠹|⠸|⠼|⠴|⠦|⠧|⠇|⠏"
    r").*$",
    re.MULTILINE,
)

LICENSE_KEYWORDS = re.compile(
    r"license|copyright|©|\bMIT\b|Apache|BSD|GPL|LGPL|MPL|SPDX|"
    r"all rights reserved|permission is hereby granted|redistribut",
    re.IGNORECASE,
)

CAT_N_LINE = re.compile(r"^(\s*\d+\t)(.*)$")
COMMENT_HASH = re.compile(r"^\s*(\d+)\t\s*#")
COMMENT_SLASH = re.compile(r"^\s*(\d+)\t\s*//")
COMMENT_BLOCK_START = re.compile(r"^\s*(\d+)\t\s*/\*")
COMMENT_BLOCK_END = re.compile(r"^\s*(\d+)\t.*\*/\s*$")
SHEBANG = re.compile(r"^\s*(\d+)\t\s*#!")

MAX_OUTPUT_LINES = 200

# Timestamps like 2026-03-23T10:15:32.123Z or [2026-03-23 10:15:32]
TIMESTAMP_PREFIX = re.compile(
    r"^(\[?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\]?\s*)"
)


def minify_json(text: str) -> str:
    """If text looks like JSON, minify it. Otherwise return unchanged."""
    stripped = text.strip()
    if not (stripped.startswith(("{", "[")) and stripped.endswith(("}", "]"))):
        return text
    try:
        parsed = json.loads(stripped)
        return json.dumps(parsed, separators=(",", ":"))
    except (json.JSONDecodeError, ValueError):
        return text


def strip_timestamp_prefixes(text: str) -> str:
    """Strip ISO timestamp prefixes from log-style output lines."""
    lines = text.split("\n")
    # Only strip if a significant portion of lines have timestamps
    ts_count = sum(1 for l in lines[:20] if TIMESTAMP_PREFIX.match(l))
    if ts_count < 3:
        return text
    return "\n".join(TIMESTAMP_PREFIX.sub("", line) for line in lines)

PKG_MANAGERS = {"npm", "npx", "yarn", "pnpm", "bun", "pip", "pip3", "pipx", "uv",
                "gem", "bundle", "cargo", "composer", "dotnet", "pod", "go",
                "poetry", "pdm", "nuget"}
TEST_RUNNERS = {"jest", "vitest", "mocha", "pytest", "rspec", "phpunit"}
BUILD_TOOLS = {"webpack", "vite", "esbuild", "tsc", "make", "cmake", "ninja",
               "gradle", "mvn", "bazel", "turbo", "nx", "lerna", "just", "task"}
LINTERS = {"eslint", "prettier", "ruff", "black", "rubocop", "clippy", "phpcs",
           "clang-format", "shfmt", "yamllint", "hadolint", "shellcheck",
           "gofmt", "rustfmt", "mypy", "pyright"}
COMPILERS = {"javac", "java", "kotlin", "kotlinc", "scala", "scalac", "sbt",
             "rustc", "gcc", "g++", "clang", "clang++"}
INTERPRETERS = {"python", "python3", "ruby", "node", "perl"}


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text)


def strip_progress_lines(text: str) -> str:
    return PROGRESS_LINE.sub("", text)


def truncate(text: str, max_lines: int = MAX_OUTPUT_LINES) -> str:
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text
    kept = lines[:max_lines]
    remaining = len(lines) - max_lines
    kept.append(f"[truncated, {remaining} more lines]")
    return "\n".join(kept)


def collapse_repetitive_lines(text: str) -> str:
    lines = text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        j = i + 1
        while j < len(lines) and lines[j] == lines[i]:
            j += 1
        count = j - i
        result.append(lines[i])
        if count >= 3:
            result.append(f"[repeated {count} times]")
            i = j
        else:
            for k in range(i + 1, j):
                result.append(lines[k])
            i = j
    return "\n".join(result)


def identify_tool(cmd: str) -> Tuple[str, str]:
    parts = cmd.strip().split()
    if not parts:
        return "unknown", "general"
    i = 0
    while i < len(parts):
        if "=" in parts[i] or parts[i] in ("sudo", "env", "time", "nice"):
            i += 1
        else:
            break
    if i >= len(parts):
        return "unknown", "general"
    base = os.path.basename(parts[i])
    if base in PKG_MANAGERS:
        rest = " ".join(parts[i:]).lower()
        if any(kw in rest for kw in ["install", "add", "update", "upgrade",
                                      "remove", "uninstall", "build"]):
            return base, "pkg_manager"
        return base, "general"
    if base in TEST_RUNNERS:
        return base, "test_runner"
    if base == "go" and len(parts) > i + 1 and parts[i + 1] == "test":
        return base, "test_runner"
    if base == "cargo" and len(parts) > i + 1 and parts[i + 1] == "test":
        return base, "test_runner"
    if base == "dotnet" and len(parts) > i + 1 and parts[i + 1] == "test":
        return base, "test_runner"
    if base == "cargo" and len(parts) > i + 1 and parts[i + 1] == "build":
        return base, "build"
    if base in BUILD_TOOLS:
        return base, "build"
    if base == "git":
        return base, "git"
    if base in ("docker", "docker-compose", "podman"):
        return base, "docker"
    if base in LINTERS:
        return base, "linter"
    if base in COMPILERS:
        return base, "compiler"
    if base in INTERPRETERS:
        return base, "interpreter"
    return base, "general"


def _collapse_blank_content_lines(lines: list, rules_fired: list) -> list:
    result = []
    blank_count = 0
    blank_start = None
    for line in lines:
        m = CAT_N_LINE.match(line)
        is_blank = m and m.group(2).strip() == "" if m else line.strip() == ""
        if is_blank:
            if blank_count == 0:
                blank_start = len(result)
            blank_count += 1
            result.append(line)
        else:
            if blank_count >= 3:
                first_blank = result[blank_start]
                result[blank_start:] = [first_blank]
                if "blank_line_collapse" not in rules_fired:
                    rules_fired.append("blank_line_collapse")
            blank_count = 0
            result.append(line)
    if blank_count >= 3:
        first_blank = result[blank_start]
        result[blank_start:] = [first_blank]
        if "blank_line_collapse" not in rules_fired:
            rules_fired.append("blank_line_collapse")
    return result


def _strip_license_header(lines: list, rules_fired: list) -> list:
    first_content_idx = None
    for i, line in enumerate(lines):
        m = CAT_N_LINE.match(line)
        if m and m.group(2).strip():
            first_content_idx = i
            break
    if first_content_idx is None:
        return lines
    first_line = lines[first_content_idx]
    if SHEBANG.match(first_line):
        first_content_idx += 1
        while first_content_idx < len(lines):
            m = CAT_N_LINE.match(lines[first_content_idx])
            if m and m.group(2).strip():
                break
            first_content_idx += 1
        if first_content_idx >= len(lines):
            return lines
        first_line = lines[first_content_idx]
    block_start = first_content_idx
    block_end = None
    if COMMENT_BLOCK_START.match(first_line):
        for i in range(block_start, len(lines)):
            if COMMENT_BLOCK_END.match(lines[i]):
                block_end = i + 1
                break
        if block_end is None:
            return lines
    elif COMMENT_HASH.match(first_line) and not SHEBANG.match(first_line):
        block_end = block_start
        for i in range(block_start, len(lines)):
            m = CAT_N_LINE.match(lines[i])
            if m:
                content = m.group(2).strip()
                if content.startswith("#") or content == "":
                    block_end = i + 1
                else:
                    break
            else:
                break
    elif COMMENT_SLASH.match(first_line):
        block_end = block_start
        for i in range(block_start, len(lines)):
            m = CAT_N_LINE.match(lines[i])
            if m:
                content = m.group(2).strip()
                if content.startswith("//") or content == "":
                    block_end = i + 1
                else:
                    break
            else:
                break
    else:
        return lines
    block_text = "\n".join(lines[block_start:block_end])
    if not LICENSE_KEYWORDS.search(block_text):
        return lines
    block_len = block_end - block_start
    marker_m = CAT_N_LINE.match(lines[block_start])
    prefix = marker_m.group(1) if marker_m else "     \t"
    marker = f"{prefix}[license header - {block_len} lines]"
    rules_fired.append("license_header_strip")
    return lines[:block_start] + [marker] + lines[block_end:]


def _strip_license_header_raw(lines: list, rules_fired: list) -> list:
    first_idx = None
    for i, line in enumerate(lines):
        if line.strip():
            first_idx = i
            break
    if first_idx is None:
        return lines
    first_line = lines[first_idx].strip()
    if first_line.startswith("#!"):
        first_idx += 1
        while first_idx < len(lines) and not lines[first_idx].strip():
            first_idx += 1
        if first_idx >= len(lines):
            return lines
        first_line = lines[first_idx].strip()
    block_start = first_idx
    block_end = None
    if first_line.startswith("/*"):
        for i in range(block_start, len(lines)):
            if "*/" in lines[i]:
                block_end = i + 1
                break
        if block_end is None:
            return lines
    elif first_line.startswith("#") and not first_line.startswith("#!"):
        block_end = block_start
        for i in range(block_start, len(lines)):
            s = lines[i].strip()
            if s.startswith("#") or s == "":
                block_end = i + 1
            else:
                break
    elif first_line.startswith("//"):
        block_end = block_start
        for i in range(block_start, len(lines)):
            s = lines[i].strip()
            if s.startswith("//") or s == "":
                block_end = i + 1
            else:
                break
    else:
        return lines
    block_text = "\n".join(lines[block_start:block_end])
    if not LICENSE_KEYWORDS.search(block_text):
        return lines
    block_len = block_end - block_start
    marker = f"[license header - {block_len} lines]"
    rules_fired.append("license_header_strip")
    return lines[:block_start] + [marker] + lines[block_end:]


def compress_read_output(tool_result: str) -> Tuple[str, List[str]]:
    rules_fired = []
    lines = tool_result.split("\n")
    is_cat_n = any(CAT_N_LINE.match(line) for line in lines[:5] if line.strip())
    if is_cat_n:
        result_lines = []
        stripped_trailing = False
        for line in lines:
            m = CAT_N_LINE.match(line)
            if m:
                prefix, content = m.group(1), m.group(2)
                cleaned = content.rstrip()
                if cleaned != content:
                    stripped_trailing = True
                result_lines.append(prefix + cleaned)
            else:
                result_lines.append(line.rstrip())
        if stripped_trailing:
            rules_fired.append("trailing_whitespace_strip")
        result_lines = _strip_license_header(result_lines, rules_fired)
        result_lines = _collapse_blank_content_lines(result_lines, rules_fired)
        return "\n".join(result_lines), rules_fired
    else:
        result_lines = []
        stripped_trailing = False
        for line in lines:
            cleaned = line.rstrip()
            if cleaned != line:
                stripped_trailing = True
            result_lines.append(cleaned)
        if stripped_trailing:
            rules_fired.append("trailing_whitespace_strip")
        result_lines = _strip_license_header_raw(result_lines, rules_fired)
        collapsed = []
        blank_count = 0
        for line in result_lines:
            if line.strip() == "":
                blank_count += 1
                if blank_count <= 1:
                    collapsed.append(line)
            else:
                if blank_count >= 3 and "blank_line_collapse" not in rules_fired:
                    rules_fired.append("blank_line_collapse")
                blank_count = 0
                collapsed.append(line)
        if blank_count >= 3 and "blank_line_collapse" not in rules_fired:
            rules_fired.append("blank_line_collapse")
        return "\n".join(collapsed), rules_fired


def compress_grep_output(tool_result: str) -> Tuple[str, List[str]]:
    rules_fired = []
    orig_len = len(tool_result)
    result = strip_ansi(tool_result)
    if len(result) != orig_len:
        rules_fired.append("ansi_strip")
    result = collapse_blank_lines(result)
    result = result.strip()
    return result, rules_fired


def compress_bash_output(cmd: str, stdout: str, stderr: str) -> Tuple[str, str, List[str]]:
    rules_fired = []
    orig_len = len(stdout)
    stdout = strip_ansi(stdout)
    stderr = strip_ansi(stderr)
    if len(stdout) != orig_len:
        rules_fired.append("ansi_strip")
    orig_len = len(stdout)
    stdout = strip_progress_lines(stdout)
    if len(stdout) != orig_len:
        rules_fired.append("progress_strip")
    stdout = collapse_blank_lines(stdout)
    _, category = identify_tool(cmd)
    if category == "general":
        orig = stdout
        stdout = collapse_repetitive_lines(stdout)
        if stdout != orig:
            rules_fired.append("repetitive_line_collapse")
    orig_lines = len(stdout.split("\n"))
    stdout = truncate(stdout)
    if len(stdout.split("\n")) != orig_lines:
        rules_fired.append("truncate")
    stdout = stdout.strip()
    stderr = stderr.strip()
    return stdout, stderr, rules_fired


def _apply_boilerplate_rules(text: str, rules_fired: List[str]) -> str:
    """Apply boilerplate stripping rules that work across all tool types."""
    # Minify JSON output
    minified = minify_json(text)
    if minified != text:
        text = minified
        rules_fired.append("json_minify")

    # Strip timestamp prefixes from log output
    stripped = strip_timestamp_prefixes(text)
    if stripped != text:
        text = stripped
        rules_fired.append("timestamp_strip")

    return text


def recompress_tool_result(tool_name: str, content: str, cmd: str = "") -> Tuple[str, List[str]]:
    """Apply appropriate compression to a tool result string based on tool type."""
    if tool_name == "Read":
        result, rules = compress_read_output(content)
    elif tool_name in ("Grep", "Glob"):
        result, rules = compress_grep_output(content)
    elif tool_name == "Bash":
        result, _stderr, rules = compress_bash_output(cmd, content, "")
    else:
        # Generic: strip ANSI and collapse blanks
        result = strip_ansi(content)
        result = collapse_blank_lines(result)
        rules = []

    # Apply cross-tool boilerplate stripping
    result = _apply_boilerplate_rules(result, rules)

    return result, rules
