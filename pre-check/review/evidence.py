#!/usr/bin/env python3
"""Deterministic evidence from the reviewer's own log (the action's execution
file, which is not uploaded): whether it read every line of diff.patch, which
tools the session had, and the usage numbers.

Usage: evidence.py EXECUTION_FILE DIFF_PATCH
Writes coverage= (full | partial | none), tools= and usage= to GITHUB_OUTPUT.
Only a fixed word, tool names and numbers leave the job.
"""

import json
import os
import re
import sys

# The Read tool numbers every line it returns: "    12\t..." (or "12→...").
NUMBERED_LINE = re.compile(r"^\s*(\d+)[\t→](.*)$", re.MULTILINE)


def _result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def coverage(messages, diff_path, lines):
    """full when successful Read results on DIFF_PATH returned every one of
    LINES (the lines of the diff) whole.

    A Read call counts only through its result: the result must not be an
    error, and a line counts only when the result shows it under its number
    with its whole text (trailing white space aside) - a failed or a short
    read never credits the range it asked for, and a line the tool truncated
    or a partial page cut inside a line never credits that line."""
    if not lines:
        return "full"
    reads = {}
    for message in messages:
        if message.get("type") != "assistant":
            continue
        for block in (message.get("message") or {}).get("content") or []:
            if (isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Read"
                    and (block.get("input") or {}).get("file_path") == diff_path and block.get("id")):
                reads[block["id"]] = True
    seen = set()
    for message in messages:
        if message.get("type") != "user":
            continue
        for block in (message.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_result" or block.get("tool_use_id") not in reads:
                continue
            if block.get("is_error"):
                continue
            for number, text in NUMBERED_LINE.findall(_result_text(block.get("content"))):
                index = int(number) - 1
                if 0 <= index < len(lines) and text.rstrip() == lines[index].rstrip():
                    seen.add(index)
    if not seen:
        return "none"
    return "full" if len(seen) == len(lines) else "partial"


def tools(messages):
    for message in messages:
        if message.get("type") == "system" and message.get("subtype") == "init":
            names = [t for t in message.get("tools") or [] if isinstance(t, str) and re.match(r"^[A-Za-z0-9_:-]{1,64}$", t)]
            return ",".join(names)
    return ""


def usage(messages):
    results = [m for m in messages if m.get("type") == "result"]
    if not results:
        return {}
    last = results[-1]
    raw = last.get("usage") or {}

    def number(value):
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    return {
        "num_turns": number(last.get("num_turns")),
        "duration_ms": number(last.get("duration_ms")),
        "total_cost_usd": number(last.get("total_cost_usd")),
        "permission_denials_count": len(last.get("permission_denials") or []),
        "usage": {key: number(raw.get(key)) for key in
                  ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")},
    }


def main(argv):
    execution_file, diff_path = argv[1:3]
    try:
        with open(execution_file, encoding="utf-8") as fh:
            messages = json.load(fh)
    except (OSError, ValueError):
        messages = []
    try:
        with open(diff_path, encoding="utf-8", newline="") as fh:
            lines = fh.read().split("\n")
    except OSError:
        lines = [""]
    if lines[-1] == "":
        lines.pop()
    messages = [m for m in messages if isinstance(m, dict)] if isinstance(messages, list) else []
    values = {"coverage": coverage(messages, diff_path, lines), "tools": tools(messages), "usage": json.dumps(usage(messages))}
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
        for key, value in values.items():
            fh.write("{}={}\n".format(key, value))
    print("Diff read: {}. Tools available: {}. Usage: {}".format(values["coverage"], values["tools"], values["usage"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
