#!/usr/bin/env python3
"""The pull requests a merge queue entry contains.

The branch of a merge group names only its last pull request
(gh-readonly-queue/main/pr-2-...), yet the group also carries every entry
ahead of it in the queue. So the membership comes from the queue itself: the
entry whose head commit is the merge group's head, and every entry ahead of
it. Taking every entry ahead can only add pull requests, never miss one; the
pull request named by the branch must be the entry found.

Usage: merge_group.py QUEUE_JSON HEAD_SHA HEAD_REF
QUEUE_JSON is the GraphQL answer for repository.mergeQueue.entries (nodes with
position, headCommit.oid and pullRequest.number). Prints the pull request
numbers, one per line; exits 1 when the membership cannot be established.
"""

import json
import re
import sys


def members(answer, head_sha, head_ref):
    try:
        nodes = answer["data"]["repository"]["mergeQueue"]["entries"]["nodes"]
    except (KeyError, TypeError):
        return None
    if not isinstance(nodes, list):
        return None
    entries = []
    for node in nodes:
        try:
            entries.append((int(node["position"]), (node.get("headCommit") or {}).get("oid"), int(node["pullRequest"]["number"])))
        except (KeyError, TypeError, ValueError):
            return None
    own = [e for e in entries if e[1] == head_sha]
    named = set(int(n) for n in re.findall(r"(?:^|/)pr-(\d+)-[0-9a-f]+$", head_ref or ""))
    if len(own) != 1 or named != {own[0][2]}:
        return None
    return sorted({number for position, _, number in entries if position <= own[0][0]})


def main(argv):
    if len(argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        with open(argv[1], encoding="utf-8") as fh:
            answer = json.load(fh)
    except (OSError, ValueError):
        return 1
    found = members(answer, argv[2], argv[3])
    if not found:
        return 1
    for number in found:
        print(number)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
