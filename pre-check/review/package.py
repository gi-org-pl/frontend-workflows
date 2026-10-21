#!/usr/bin/env python3
"""Packages the reviewer's result and the scope for the review job.

They travel as a short-lived artifact, not as job outputs: an environment
string is limited to about 128 KiB on Linux, and a result or a scope within
the declared limits can be larger.

The artifact belongs to a public run, so what goes into it is already as safe
to show as the published comment: every string of the result is redacted,
and a result in which anything still looks like a credential is replaced by
{"withheld": true} - evaluate.py turns that into the "human" outcome without
the text ever leaving this job.

Usage: package.py EXECUTION_FILE SCOPE_JSON OUT_DIR
Writes OUT_DIR/result.json (only when the run returned a result) and
OUT_DIR/scope.json.
"""

import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from evaluate import leaks, redact  # noqa: E402


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)


def redacted(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redacted(item) for item in value]
    if isinstance(value, dict):
        return {key: redacted(item) for key, item in value.items()}
    return value


def structured_output(messages):
    results = [m for m in messages if isinstance(m, dict) and m.get("type") == "result"]
    if not results:
        return None
    return results[-1].get("structured_output")


def package(result):
    if result is None:
        return None
    if any(leaks(redact(text)) for text in strings(result)):
        return {"withheld": True}
    return redacted(result)


def main(argv):
    execution_file, scope_file, out_dir = argv[1:4]
    os.makedirs(out_dir, exist_ok=True)
    try:
        with open(execution_file, encoding="utf-8") as fh:
            messages = json.load(fh)
    except (OSError, ValueError):
        messages = []
    result = package(structured_output(messages if isinstance(messages, list) else []))
    if result is not None:
        with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as fh:
            json.dump(result, fh)
    if os.path.exists(scope_file):
        shutil.copyfile(scope_file, os.path.join(out_dir, "scope.json"))
    print("Packaged: result {}, scope {}.".format(
        "withheld" if result == {"withheld": True} else ("present" if result is not None else "missing"),
        "present" if os.path.exists(scope_file) else "missing"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
