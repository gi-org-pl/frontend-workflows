#!/usr/bin/env python3
"""The contracts of the front-end pre-check, in one place.

- OUTCOMES: the one set of outcome states, with whether the required check
  passes and which label is set. Every component takes them from here.
- SCOPE_RULES: what the collected scope alone decides about the outcome -
  "human" when the change under review was not fully seen, "advisory" when
  only linked context (issues beyond the cap, linked documents) was not.
- validate(): a small JSON-schema validator for the subset the pre-check's
  schemas use (type, properties, required, additionalProperties, enum, items,
  minItems, maxItems, maxLength, minimum, maximum), so that the collected
  scope and the reviewer's output are checked at each boundary without
  installing a package on the runner.

Command line, for report.sh:
  contracts.py passes OUTCOME   exit 0 if the check passes, 1 otherwise
  contracts.py label OUTCOME    print the label ("" for none)
  contracts.py labels           print every label, one per line
  contracts.py validate SCHEMA FILE   exit 0 if FILE matches SCHEMA
  contracts.py fingerprint PR_JSON    print the fingerprint of a pull request
"""

import hashlib
import json
import sys

# Outcome -> (does frontend-pre-check / review pass, label)
OUTCOMES = {
    "clean": (True, "pre-check: clean"),          # no findings, full deterministic coverage
    "advisory": (True, "pre-check: advisory"),    # only non-blocking findings, full coverage
    "queued": (True, ""),                         # merge queue entry whose PRs passed on their heads
    "changes": (False, "pre-check: changes"),     # at least one blocking finding
    # A rule says a person must judge it (incl. withheld output). It passes:
    # the pull request's required approval by a person is the gate, and the
    # label, the comment and a warning annotation say that it needs one.
    # report.sh lets it pass only where a ruleset requires an approval of the
    # current head; elsewhere the run fails as before.
    "human": (True, "pre-check: human review"),
    "unqueued": (False, ""),                      # merge queue entry with a pull request that has not passed on its head
    "invalid": (False, ""),                       # no valid result: the run failed, the output was malformed, or the input was refused
    "skipped": (False, ""),                       # not pre-checked: fork, draft, bot, no write access, no secret, run limit
}

# (the outcome a rule forces at least, the reason shown, the test on the scope)
# "human": the change itself, or context it depends on, was not fully seen -
# a person has to judge. "advisory": linked context the reviewer did not get
# in full; the check still passes, but never as "clean".
SCOPE_RULES = (
    ("human", "no file of it could be reviewed", lambda s: s["file_count"] > 0 and not s["reviewed"]),
    ("human", "the pull request is too large for a full pre-check", lambda s: s["truncated"]),
    ("human", "some changes have no reviewable diff", lambda s: bool(s["unreviewable"])),
    ("human", "it changes CI workflows", lambda s: bool(s["workflow_changes"])),
    ("human", "it changes code owners, dependencies or build configuration",
     lambda s: any(not p["path"].startswith((".github/workflows/", ".github/actions/")) for p in s["human_paths"])),
    ("human", "some context of the change was cut at its size limit or could not be read",
     lambda s: bool(s["cut_sources"])),
    ("advisory", "some linked context was not read in full", lambda s: bool(s["unread_context"])),
)


def scope_reasons(scope, level):
    """The reasons of the SCOPE_RULES of LEVEL ("human" or "advisory") that hold."""
    return [reason for rule_level, reason, holds in SCOPE_RULES if rule_level == level and holds(scope)]


LABEL_COLOURS = {
    "pre-check: clean": ("0e8a16", "AI pre-check reported no findings; not an approval"),
    "pre-check: advisory": ("c2e0c6", "AI pre-check passed with advisory findings; not an approval"),
    "pre-check: changes": ("d93f0b", "AI pre-check found something to fix"),
    "pre-check: human review": ("fbca04", "AI pre-check cannot judge this pull request; a person reviews it"),
}

_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool, "null": type(None),
}


def _is_type(value, name):
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPES[name])


def errors(value, schema, path="$"):
    """Returns a list of violations of SCHEMA by VALUE (empty when valid)."""
    found = []
    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        if not any(_is_type(value, n) for n in names):
            return ["{}: expected {}".format(path, "/".join(names))]
    if "enum" in schema and value not in schema["enum"]:
        found.append("{}: not one of {}".format(path, schema["enum"]))
    if isinstance(value, str):
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            found.append("{}: longer than {}".format(path, schema["maxLength"]))
    if _is_type(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            found.append("{}: below {}".format(path, schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            found.append("{}: above {}".format(path, schema["maximum"]))
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            found.append("{}: more than {} items".format(path, schema["maxItems"]))
        if "minItems" in schema and len(value) < schema["minItems"]:
            found.append("{}: fewer than {} items".format(path, schema["minItems"]))
        if "items" in schema:
            for i, item in enumerate(value):
                found += errors(item, schema["items"], "{}[{}]".format(path, i))
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                found.append("{}: missing {}".format(path, key))
        for key, item in value.items():
            if key in props:
                found += errors(item, props[key], "{}.{}".format(path, key))
            elif schema.get("additionalProperties") is False:
                found.append("{}: unexpected {}".format(path, key))
            elif isinstance(schema.get("additionalProperties"), dict):
                found += errors(item, schema["additionalProperties"], "{}.{}".format(path, key))
    return found


def validate(value, schema):
    return not errors(value, schema)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def fingerprint(pr):
    """What a review depends on that can change without a push and still
    starts a new run: the description and the draft state. A run publishes
    only while the pull request still has the fingerprint it reviewed. The
    head and the base are checked on their own; the title is left out, as a
    title-only edit does not start a run."""
    data = json.dumps({"body": pr.get("body") or "", "draft": bool(pr.get("draft"))}, sort_keys=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def main(argv):
    command = argv[1] if len(argv) > 1 else ""
    if command == "fingerprint":
        print(fingerprint(load(argv[2])))
        return 0
    if command == "passes":
        return 0 if OUTCOMES.get(argv[2], (False, ""))[0] else 1
    if command == "label":
        print(OUTCOMES.get(argv[2], (False, ""))[1])
        return 0
    if command == "labels":
        for label in LABEL_COLOURS:
            colour, description = LABEL_COLOURS[label]
            print("{}\t{}\t{}".format(label, colour, description))
        return 0
    if command == "validate":
        try:
            problems = errors(load(argv[3]), load(argv[2]))
        except (OSError, ValueError) as error:
            problems = [str(error)]
        for problem in problems[:20]:
            print(problem, file=sys.stderr)
        return 0 if not problems else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
