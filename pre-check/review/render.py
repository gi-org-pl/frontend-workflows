#!/usr/bin/env python3
"""Presents a pre-check run: the Pre-check comment and the inline comments.

Presentation only. The outcome comes from evaluate.py, computed from the
complete result before anything here is shortened; nothing in this file can
change whether the check passes.

Everything the reviewer wrote is rendered as escaped plain text: no links of
any kind, no images, no HTML, no mentions, no Markdown structure, no
suggestion blocks; fenced and inline code stay literal. Known credential
shapes are redacted. The only links are the ones built here from the scope,
each checked by allowed_link().

Usage:
  render.py RESULT_JSON SCOPE_JSON EVALUATION_JSON OUT_DIR   writes comment.md and inline.json
  render.py withheld EVALUATION_JSON OUT_DIR                 writes the notice that replaces a withheld result
Environment: HEAD_SHA, RUN_URL, MODEL, WORKFLOW_SHA, COVERAGE.
"""

import hashlib
import json
import os
import re
import sys
from urllib.parse import quote, unquote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import contracts  # noqa: E402
from evaluate import redact  # noqa: E402

MARKER = "<!-- gi-pre-check -->"
FINDING_MARKER = "<!-- gi-pre-check-finding {} -->"
MAX_COMMENT = 60000
MAX_ITEMS = 20
MAX_SHOWN = 30
MAX_INLINE = 15
MAX_BODY = 3000
MAX_LOOK = 5      # decisions shown outside the folded list
MAX_QA = 5        # QA steps shown
MAX_LISTED = 10   # guide documents named in the scope line
HEADLINES = {
    "clean": "✅ clean",
    "advisory": "✅ passed",
    "changes": "❌ changes needed",
    "human": "⚠️ needs a person",
    "invalid": "❌ not finished",
    "skipped": "⏭️ not pre-checked",
    "queued": "✅ queued",
    "unqueued": "❌ not queued",
}
DOTS = {"blocking": "🔴", "non-blocking": "🟡"}
IMPORTANCE = {"high": 0, "medium": 1, "low": 2}
SAFE_PATH = re.compile(r"^[A-Za-z0-9._@+-]+(/[A-Za-z0-9._@+-]+)*$")

LINK_SHAPE = re.compile(
    r"^https://(github\.com/gi-org-pl/|gi\.org\.pl/|(www\.)?figma\.com/)[A-Za-z0-9._~/?=&%:+#-]*$"
)
ALLOWED_HOSTS = {"github.com", "gi.org.pl", "figma.com", "www.figma.com"}
CATEGORIES = [
    ("data_structures", "Data structures"),
    ("state", "State"),
    ("api_contracts", "API contracts"),
    ("ux_behaviours", "UX behaviours"),
    ("new_dependencies", "New dependencies"),
    ("architecture", "Architecture"),
]
ZWSP = "​"
MARKDOWN_PUNCTUATION = re.compile(r"([\\`*_{}\[\]()#+\-.!|~=:\"'])")


def allowed_link(url):
    """True for a link to an allowlisted place, and only there: the shape,
    then the host (no user information, no port), then the path percent-decoded
    until stable (catching %252e) without ".", ".." or empty segments or a
    backslash; github.com only under /gi-org-pl/."""
    if not isinstance(url, str) or not LINK_SHAPE.match(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    netloc = parts.netloc.lower()
    if parts.scheme != "https" or "@" in netloc or ":" in netloc or netloc not in ALLOWED_HOSTS:
        return False
    path = parts.path
    for _ in range(10):
        decoded = unquote(path)
        if decoded == path:
            break
        path = decoded
    else:
        return False
    if "\\" in path or "//" in path or path.startswith("/.."):
        return False
    if any(segment in (".", "..") for segment in path.split("/")):
        return False
    if netloc == "github.com" and not path.startswith("/gi-org-pl/"):
        return False
    return True


def plain(text):
    """Escaped plain text: no HTML, entities, mentions, links or Markdown."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = MARKDOWN_PUNCTUATION.sub(r"\\\1", text)
    text = re.sub(r"(?i)([a-z][a-z0-9+\\.-]*)\\:/", lambda m: m.group(1) + "\\:" + ZWSP + "/", text)
    text = re.sub(r"(?i)\bwww\\\.", "www" + ZWSP + "\\.", text)
    return text.replace("@", "@" + ZWSP)


def code_span(text):
    text = text.replace("`", "'").replace("\n", " ")
    return "`" + text + "`" if text.strip() else ""


def escape_line(text):
    """One line: inline code spans stay literal, everything else is plain."""
    parts = text.split("`")
    if len(parts) % 2 == 0:  # an unterminated span is plain text
        last = parts.pop()
        parts[-1] = parts[-1] + "`" + last
    return "".join(code_span(p) if i % 2 == 1 else plain(p) for i, p in enumerate(parts))


def one_line(value, limit):
    text = redact(" ".join(str(value).split()))
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return escape_line(text)


def multi_line(value, limit):
    """A body: fenced code stays literal (suggestion blocks become plain code),
    everything else is escaped line by line."""
    text = redact(str(value).replace("\r", ""))
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    out, fence = [], None
    for line in text.split("\n"):
        match = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if fence is None and match:
            fence = match.group(1)
            out.append(fence)
            continue
        if fence is not None:
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence) and not match.group(2).strip():
                out.append(fence)
                fence = None
            else:
                out.append(line.replace("\t", "    "))
            continue
        out.append(escape_line(line))
    if fence is not None:
        out.append(fence)
    return "\n".join(out)


def code(name):
    return "`{}`".format(str(name).replace("`", "'"))


def cell(text):
    """Text for a table cell: a pipe would end the cell, also inside a code
    span. A pipe plain() already escaped stays escaped once."""
    return re.sub(r"(?<!\\)\|", r"\\|", text)


def fingerprint(f):
    identity = "\n".join([f["path"], str(f.get("line") or ""), f.get("side", "RIGHT"), " ".join(f["title"].lower().split())])
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def footer():
    head = re.sub(r"[^0-9a-f]", "", os.environ.get("HEAD_SHA", ""))[:7]
    model = re.sub(r"[^A-Za-z0-9._-]", "", os.environ.get("MODEL", ""))[:64] or "default"
    workflow = re.sub(r"[^0-9a-f]", "", os.environ.get("WORKFLOW_SHA", ""))[:40]
    run_url = os.environ.get("RUN_URL", "")
    run = "[run]({})".format(run_url) if allowed_link(run_url) else "run"
    instructions = "https://github.com/gi-org-pl/frontend-workflows/blob/{}/docs/pre-check/REVIEWER.md".format(workflow)
    return "\n\n<sub>AI pre-check of `{}` · `{}` · {} · [instructions]({}) · advisory, not an approval</sub>".format(
        head, model, run, instructions if allowed_link(instructions) else "")


def count_line(evaluation):
    blocking, minor = evaluation["blocking"], evaluation["advisory"]
    if not blocking and not minor:
        return "no findings"
    parts = (["{} blocking".format(blocking)] if blocking else []) + (["{} minor".format(minor)] if minor else [])
    return ", ".join(parts) + (" finding" if blocking + minor == 1 else " findings")


def headline(evaluation):
    """The heading: icon, outcome, the reason in a few words, the count. The
    reasons are fixed texts of contracts.py and evaluate.py, never model text."""
    outcome = evaluation["outcome"]
    text = HEADLINES[outcome]
    if outcome == "human":
        text += " ({})".format("; ".join(evaluation["reasons"]))
    return "## Pre-check: {} · {}".format(text, count_line(evaluation))


def status_lines(evaluation):
    outcome = evaluation["outcome"]
    if outcome == "human":
        return ["The check passes: this pull request needs a person's review and approval, which is the gate. "
                "This is not an approval."]
    if outcome == "changes" and evaluation["reasons"]:
        return ["A person has to look at it in any case: " + "; ".join(evaluation["reasons"]) + "."]
    if outcome == "advisory" and evaluation.get("notes"):
        return ["Not clean: " + "; ".join(evaluation["notes"]) + " (see Scope below)."]
    return []


def where(f, scope):
    """file:line of a finding, linked to the commit it is about - the link is
    built here from the scope, never taken from the model."""
    path, line, side = f["path"], f.get("line"), f.get("side", "RIGHT")
    label = path.rsplit("/", 1)[-1] + (":{}".format(line) if line else "")
    repo = os.environ.get("REPO", "")
    changed = set(scope["hunks"]) | set(scope["reviewed"]) | {u["path"] for u in scope["unreviewable"]}
    sha = scope["base"] if side == "LEFT" else scope["head"]
    # A removed line lives in the base commit, under the old name of a renamed file.
    target = path
    if side == "LEFT":
        target = next((r["from"] for r in scope["renamed"] if r["to"] == path), path)
    if (path in changed and SAFE_PATH.match(target) and re.match(r"^gi-org-pl/[A-Za-z0-9._-]+$", repo)
            and re.match(r"^[0-9a-f]{40}$", sha)):
        url = "https://github.com/{}/blob/{}/{}{}".format(repo, sha, quote(target), "#L{}".format(line) if line else "")
        if allowed_link(url):
            return "[{}]({})".format(plain(label), url)
    return code(label)


def ranked_decisions(result):
    """Every decision with its category, the most important first, otherwise
    in the order of the categories and of the reviewer's list."""
    rows = [(IMPORTANCE.get(d["importance"], 3), i, label, d)
            for i, (key, label) in enumerate(CATEGORIES) for d in result["decisions"][key]]
    return [(label, d) for _, _, label, d in sorted(rows, key=lambda r: (r[0], r[1]))]


def decision_line(d):
    return "- **{}** {}".format(one_line(d["lead"], 80), one_line(d["detail"], 400))


def scope_lines(result, scope, coverage):
    reading = {"full": "read in full", "partial": "not read in full", "none": "reading not observed"}.get(coverage, "reading not observed")
    checked = "- Checked: {} file(s), {} changed lines of {} against {} ({}); gi-tech-standards {}".format(
        len(scope["reviewed"]), scope["diff_lines"], code(scope["head"][:7]), code(scope["base"][:7]), reading,
        code(scope["standards"][:7]))
    if scope["repo_docs"]:
        checked += "; the repository guide: " + ", ".join(code(d) for d in scope["repo_docs"][:MAX_LISTED])
        if len(scope["repo_docs"]) > MAX_LISTED:
            checked += " and {} more".format(len(scope["repo_docs"]) - MAX_LISTED)
    lines = [checked + "."]
    lines.append("- Linked issues read: " + (", ".join(code(i) for i in scope["issues"]) if scope["issues"] else "none found")
                 + " (members of the organisation only).")
    if scope["docs"]:
        lines.append("- Linked documents read: " + ", ".join(code(d) for d in scope["docs"]) + ".")
    lines += ["- " + one_line(item, 400) for item in result["checked"][:MAX_ITEMS]]

    lines.append("- Not checked: runtime behaviour - nothing was built, run or tested.")
    if scope["truncated"]:
        text = "- **Too large for a full pre-check** (cap: {} changed lines).".format(scope["max_diff_lines"])
        if scope["not_reviewed"]:
            text += " Not reviewed: " + ", ".join(code(n) for n in scope["not_reviewed"]) + "."
        lines.append(text)
    lines += ["- No reviewable diff: {} - {}.".format(code(u["path"]), u["reason"]) for u in scope["unreviewable"]]
    lines += ["- Needs a person: {} - {}.".format(code(u["path"]), u["reason"]) for u in scope["human_paths"]]
    lines += ["- Renamed or copied: {} to {}.".format(code(r["from"]), code(r["to"])) for r in scope["renamed"]]
    if scope["safe_assets"]:
        lines.append("- Images, listed but not inspected: " + ", ".join(code(n) for n in scope["safe_assets"]) + ".")
    if scope["figma"]:
        links = " ".join("[{}]({})".format(i + 1, url) for i, url in enumerate(scope["figma"]) if allowed_link(url))
        lines.append("- Figma: judged only from the design comparison in the description; the reviewer sees neither Figma nor images. Links: " + links + ".")
    lines += ["- Cut at its size limit or not available: " + one_line(c, 200) + "." for c in scope["cut_sources"]]
    lines += ["- Linked context not read in full (does not need a person by itself): " + one_line(u, 400) + "."
              for u in scope["unread_context"]]
    lines += ["- " + one_line(n, 400) for n in scope["notes"]]
    lines += ["- " + one_line(item, 400) for item in result["not_checked"][:MAX_ITEMS]]
    if scope["excluded"]:
        lines += ["", "<details><summary>Left out of the diff by policy: {} file(s), {} changed lines</summary>".format(
            len(scope["excluded"]), scope["excluded_lines"]), ""]
        lines += ["- " + code(n) for n in scope["excluded"]]
        lines += ["", "</details>"]
    return lines


def details(summary, body_lines):
    return ["", "<details><summary>{}</summary>".format(summary), ""] + body_lines + ["", "</details>"]


def render(result, scope, evaluation, coverage):
    findings = result["findings"]
    shown = sorted(findings, key=lambda f: f["severity"] != "blocking")[:MAX_SHOWN]

    def in_diff(f):
        side = f.get("side", "RIGHT")
        return bool(f.get("line")) and any(h[side][0] <= f["line"] <= h[side][1] for h in scope["hunks"].get(f["path"], []))

    body_limit = MAX_BODY if len(shown) <= 10 else 1200
    inline, rows, entries = [], [], []
    for f in shown:
        fp = fingerprint(f)
        dot = DOTS[f["severity"]]
        title = one_line(f["title"], 90)
        body = multi_line(f.get("body", ""), body_limit)
        marker = ""
        if f.get("inline") and in_diff(f) and len(inline) < MAX_INLINE:
            inline.append({
                "path": f["path"], "line": f["line"], "side": f.get("side", "RIGHT"), "fingerprint": fp,
                "body": "{} **[{}]** {}\n\n{}\n\nThe Pre-check comment of this pull request holds every finding.\n\n{}".format(
                    dot, f["severity"], title, body, FINDING_MARKER.format(fp)),
            })
            # report.sh replaces the marker once it knows whether the comment
            # was attached; model text cannot contain "<", so cannot forge one.
            marker = "<!-- inline {} -->".format(fp)
        rows.append("| {} | {} | {} |".format(dot, cell(title), cell(where(f, scope))))
        location = code(f["path"] + (":{}".format(f["line"]) if f.get("line") else ""))
        entries.append("**{} {}** - {}{}\n\n{}".format(dot, title, location, marker, body or "(no details given)"))

    lines = [headline(evaluation), "", one_line(result["summary"], 200)]
    status = status_lines(evaluation)
    if status:
        lines += [""] + status
    if rows:
        lines += ["", "**Findings**", "", "| | Finding | Where |", "|---|---|---|"] + rows
        if len(findings) > len(shown):
            lines += ["", "{} findings were returned; the first {} are shown, blocking ones first. The heading counts all of them.".format(
                len(findings), len(shown))]

    ranked = ranked_decisions(result)
    if ranked:
        lines += ["", "**Decisions to look at**", ""] + [decision_line(d) for _, d in ranked[:MAX_LOOK]]
    lines += ["", "**For QA**", ""]
    qa = result["qa"][:MAX_QA]
    lines += ["{}. {}".format(i + 1, one_line(step, 300)) for i, step in enumerate(qa)] or ["Nothing specific beyond the issue's acceptance criteria."]

    if entries:
        lines += details("Finding details ({})".format(len(shown)), ["\n\n".join(entries)])
    all_decisions = []
    for key, label in CATEGORIES:
        items = result["decisions"][key][:MAX_ITEMS]
        all_decisions += ["", "**{}**".format(label), ""] + ([decision_line(d) for d in items] or ["- None."])
    lines += details("All technical decisions ({})".format(len(ranked)), all_decisions[1:])
    lines += details("Scope: what was and was not checked", scope_lines(result, scope, coverage))

    body = "\n".join(lines)
    if len(body) > MAX_COMMENT:
        body = body[:MAX_COMMENT] + "\n\n(The rest was cut: the comment would be too long. The heading counts every finding.)"
    return MARKER + "\n" + body + footer() + "\n", inline


def withheld_notice():
    return (MARKER + "\n## Pre-check: ⚠️ needs a person (the reviewer's output was withheld)\n\nThe reviewer's output "
            "contains text that looks like a credential, so it is not published. A person reviews the pull request; ask "
            "an organisation owner to look at the workflow run if a credential may be involved." + footer() + "\n")


def main(argv):
    if len(argv) == 4 and argv[1] == "withheld":
        with open(os.path.join(argv[3], "comment.md"), "w", encoding="utf-8") as fh:
            fh.write(withheld_notice())
        with open(os.path.join(argv[3], "inline.json"), "w", encoding="utf-8") as fh:
            fh.write("[]")
        return 0
    if len(argv) != 5:
        print(__doc__, file=sys.stderr)
        return 2
    result, scope, evaluation = (contracts.load(p) for p in argv[1:4])
    if evaluation["outcome"] == "invalid":
        return 1
    comment, inline = render(result, scope, evaluation, os.environ.get("COVERAGE", "none"))
    with open(os.path.join(argv[4], "comment.md"), "w", encoding="utf-8") as fh:
        fh.write(comment)
    with open(os.path.join(argv[4], "inline.json"), "w", encoding="utf-8") as fh:
        json.dump(inline, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
