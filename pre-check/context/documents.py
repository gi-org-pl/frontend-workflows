"""The text context of a review: the pull request description, linked issues,
linked documents and the repository's guide.

All of it is untrusted, whoever wrote it. What people wrote is wrapped in
quoted-data markers with a nonce its author cannot know (provenance, not a
security boundary); only issues of the organisation and only what its members
wrote are used; documents come only from the default branch of an allowed
repository, pinned to a commit; every cut at a size limit is recorded.
"""

import bisect
import os
import re

from github import GitHubError

TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
MAX_ISSUES = 10
MAX_COMMENTS = 50
MAX_COMMENT_CHARS = 8000
MAX_ISSUE_BYTES = 60000
MAX_BODY_BYTES = 60000
MAX_DOC_FILES = 20
MAX_FILE_BYTES = 200000
MAX_GUIDE_DOCS = 40
SCOPED_GUIDE = re.compile(r"(^|/)(AGENTS|CLAUDE)\.md$")
SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
GUIDE = re.compile(r"(^|/)(AGENTS|CLAUDE)\.md$|^(README\.md|CONTRIBUTING\.md|docs/.*\.mdx?|\.github/pull_request_template\.md)$")
FIGMA = re.compile(r"https://([a-z]+\.)?figma\.com/[A-Za-z0-9._~/?=&%:+-]+")


class Context:
    """Collects notes, cut sources and unread context while the pieces are
    gathered. cut_sources: context of the change itself (the description,
    issues, the repository's guide) that was cut or could not be read - the
    result needs a person. unread: linked context (issues beyond the cap,
    linked documents) that was not read in full - listed, and the result
    passes as "advisory" at best (contracts.SCOPE_RULES)."""

    def __init__(self, nonce):
        self.nonce = nonce
        self.notes = []
        self.cut_sources = []
        self.unread = []

    def quote(self, label, data, limit, linked=False):
        """LINKED: a linked document, whose cut is unread context, not a cut source."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        if len(data) > limit:
            if linked:
                self.unread.append("{} (cut at its size limit: the first {} KB of {} KB read)".format(
                    label, limit // 1000, (len(data) + 999) // 1000))
            else:
                self.cut_sources.append(label)
            data = data[:limit]
        text = data.decode("utf-8", errors="ignore")  # a cut never leaves half a character
        return "BEGIN QUOTED DATA {} ({})\n{}\nEND QUOTED DATA {}\n".format(self.nonce, label, text, self.nonce)


def safe_relpath(path):
    """A plain relative path: no empty, "." or ".." segment, no leading slash
    or backslash, a plain character set."""
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        return False
    return all(SEGMENT.match(s) and s not in (".", "..") for s in path.split("/"))


def inside(target, base):
    target, base = os.path.realpath(target), os.path.realpath(base)
    return target.startswith(base + os.sep)


CLOSING_WORD = r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)"
# An issue number has no leading zero and is not followed by a letter, so a
# colour such as #004554 or #12ab34 is not read as an issue.
NUMBER = r"([1-9][0-9]*)(?![0-9A-Za-z_])"
REF_IN_BODY = r"(?:https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/|((?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?)#)" + NUMBER
# A short reference that is the value of a colour declaration ("color: #333",
# "fill='#fff'") is a colour, not an issue; a mention near the word ("the
# color bug #123") stays a reference.
COLOUR_CONTEXT = re.compile(r"(?i)\b(?:colou?r|background|fill|stroke|border|outline|accent)(?:-[a-z]+)*\s*[:=]\s*[\"']?$")


QUOTE_MARKER = re.compile(r"^ {0,3}>[ ]?")
LIST_MARKER = re.compile(r"^ {0,3}(?:[-*+]|[0-9]{1,9}[.)])(?: +|$)")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def without_code(text):
    """TEXT without fenced code blocks and inline code spans, where a "#123"
    is code, not a reference."""
    # Fenced blocks, as Markdown reads them inside their containers: a stack of
    # block quotes and list items in any order ("- > ~~~"). Each line first
    # continues the open containers (a quote by its ">", an item by its
    # indentation; a blank line keeps items open), then opens new ones. A fence
    # is indented by at most three spaces within its containers (with four it
    # is indented code). A block closes at a run of the same character at
    # least as long as the opener with nothing else on the line, or when a
    # container it opened in ends; an unclosed block otherwise runs to the end.
    # Inside a block only its containers are read: the rest is code.
    kept, stack, fence = [], [], None  # stack: ">" or an item's content indent; fence: (character, length, depth)
    for line in text.split("\n"):
        # A tab counts as indentation to the next multiple of four columns.
        rest, matched = line.expandtabs(4), 0
        for container in stack:
            if container == ">":
                match = QUOTE_MARKER.match(rest)
                if not match:
                    break
                rest = rest[match.end():]
            elif rest.strip():
                if len(rest) - len(rest.lstrip(" ")) < container:
                    break
                rest = rest[container:]
            matched += 1
        if fence is not None:
            if matched >= fence[2]:
                match = FENCE.match(rest)
                if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= fence[1] and not match.group(2).strip():
                    fence = None
                continue
            fence = None  # a container of the block ended; this line is read as usual
        del stack[matched:]
        while rest.strip():
            match = QUOTE_MARKER.match(rest)
            if match:
                stack.append(">")
            else:
                match = LIST_MARKER.match(rest)
                if not match:
                    break
                stack.append(match.end())
            rest = rest[match.end():]
        if not rest.strip():
            # Nothing but container markers: a blank line of its container, which
            # ends the paragraph (a code span never crosses one).
            kept.append("")
            continue
        match = FENCE.match(rest)
        if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
            fence = (match.group(1)[0], len(match.group(1)), len(stack))
            continue
        kept.append(line)
    text = "\n".join(kept)
    return without_code_spans(text)


BLANK_LINE = re.compile(r"\n[ \t]*\n")


def without_code_spans(text):
    """TEXT without inline code spans, read left to right as Markdown does: a
    span opens at a run of backticks that is not backslash-escaped and closes
    at the next run of the same length within the paragraph (inside a span a
    backslash escapes nothing); an escaped backtick is text."""
    out, i, closers = [], 0, {}
    blanks = [m.start() for m in BLANK_LINE.finditer(text)]  # paragraph ends, found once
    while i < len(text):
        char = text[i]
        if char == "\\" and i + 1 < len(text):
            out.append(text[i:i + 2])
            i += 2
            continue
        if char != "`":
            out.append(char)
            i += 1
            continue
        end = i
        while end < len(text) and text[end] == "`":
            end += 1
        run = end - i
        closer = closers.setdefault(run, re.compile(r"(?<!`)`{%d}(?!`)" % run))
        following = bisect.bisect_left(blanks, end)
        match = closer.search(text, end, blanks[following] if following < len(blanks) else len(text))
        if match:
            out.append(" ")
            i = match.end()
        else:
            out.append(text[i:end])  # no closing run: the backticks are text
            i = end
    return "".join(out)


def issue_refs(body, closing, repo):
    """Candidate references, unique, in the order they are read: the issues
    the pull request closes (GitHub's closing references, then the ones the
    description names after "closes", "fixes" or "resolves"), then the other
    mentions in order. Code and colours are not references."""
    body = without_code(body)
    found = list(closing)
    for m in re.finditer(r"(?i)\b" + CLOSING_WORD + r":?\s+" + REF_IN_BODY, body):
        found.append("{}#{}".format(m.group(1) or m.group(2) or repo, m.group(3)))
    found += ["{}#{}".format(m.group(1), m.group(2)) for m in
              re.finditer(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/" + NUMBER, body)]
    for m in re.finditer(r"(?:^|[^A-Za-z0-9_/.-])((?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?)#" + NUMBER, body):
        # Only the few characters before the "#": a declaration is short, and
        # searching the whole prefix for every reference would be quadratic.
        if not m.group(1) and COLOUR_CONTEXT.search(body[max(0, m.start(2) - 41):m.start(2) - 1]):
            continue
        found.append("{}#{}".format(m.group(1) or repo, m.group(2)))
    seen, out = set(), []
    for ref in found:
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def valid_ref(ref, owner):
    match = re.match(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#([1-9][0-9]{0,6})$", ref)
    if not match:
        return False
    ref_owner, name, _ = match.groups()
    return ref_owner == owner and NAME.match(name) and name not in (".", "..")


def collect_issues(gh, ctx, refs, owner, out_dir):
    """Writes the issues to OUT_DIR, returns (issue refs, text to search for links)."""
    issues, not_read, outside, links = [], [], 0, ""
    for ref in refs:
        if not valid_ref(ref, owner):
            continue
        if len(issues) >= MAX_ISSUES:
            not_read.append(ref)
            continue
        repo, number = ref.split("#")
        # A linked source that cannot be read (an API failure, or a private
        # repository the caller's token cannot see) goes to cut_sources: the
        # reviewer would judge without it, so the result needs a person.
        try:
            issue = gh.api("repos/{}/issues/{}".format(repo, number))
        except GitHubError:
            ctx.cut_sources.append("the linked issue {} (it could not be read)".format(ref))
            continue
        if "pull_request" in issue:
            continue
        try:
            comments = gh.api("repos/{}/issues/{}/comments?per_page=100".format(repo, number), paginate=True)
        except GitHubError:
            comments = []
            ctx.cut_sources.append("the comments of issue {} (they could not be read)".format(ref))
        trusted = [c for c in comments if c.get("author_association") in TRUSTED]
        outside += len(comments) - len(trusted)
        if issue.get("author_association") in TRUSTED:
            text = "Title: {}\nState: {}\n\n{}".format(issue.get("title", ""), issue.get("state", ""), issue.get("body") or "(empty)")
        else:
            text = "State: {}\n\n(The issue was opened by someone outside the organisation; its title and description are left out.)".format(issue.get("state", ""))
        cut_comments = len(trusted) > MAX_COMMENTS
        for c in trusted[:MAX_COMMENTS]:
            body = c.get("body") or ""
            if len(body) > MAX_COMMENT_CHARS:
                body, cut_comments = body[:MAX_COMMENT_CHARS] + "\n(cut)", True
            text += "\n\n--- Comment by {} ({}), {}\n\n{}".format(
                c.get("user", {}).get("login", ""), c.get("author_association", ""), c.get("created_at", ""), body)
        if cut_comments:
            ctx.cut_sources.append("comments of issue {}".format(ref))
        name = "{}-{}.md".format(repo.replace("/", "-"), number)
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            fh.write("# Issue {}\n\n".format(ref) + ctx.quote("issue " + ref, text, MAX_ISSUE_BYTES))
        issues.append(ref)
        links += "\n" + text[:MAX_ISSUE_BYTES]
    if not_read:
        ctx.unread.append("linked issues beyond the first {}, not read: {}".format(MAX_ISSUES, " ".join(not_read)))
    if outside:
        ctx.notes.append("{} comment(s) on the linked issues by people outside the organisation were left out.".format(outside))
    return issues, links


def figma_links(text):
    seen, out = set(), []
    for m in FIGMA.finditer(text):
        if m.group(0) not in seen:
            seen.add(m.group(0))
            out.append(m.group(0))
    return out[:20]


def resolve_ref(gh, repo, ref, cache):
    """The commit of REF if it is the default branch or a commit on it."""
    if repo not in cache:
        branch = gh.api("repos/{}".format(repo))["default_branch"]
        cache[repo] = (branch, gh.api("repos/{}/commits/{}".format(repo, branch))["sha"])
    branch, sha = cache[repo]
    if ref == branch:
        return sha
    if re.match(r"^[0-9a-f]{7,40}$", ref):
        status = gh.api("repos/{}/compare/{}...{}".format(repo, ref, sha)).get("status")
        if status in ("ahead", "identical"):
            return ref
    return None


def collect_documents(gh, ctx, text, doc_repos, owner, out_dir):
    docs, skipped, cache = [], [], {}

    def fetch(repo, sha, path):
        if len(docs) >= MAX_DOC_FILES:
            skipped.append("{}/{}".format(repo, path))
            return
        target = os.path.join(out_dir, repo, path)
        if not safe_relpath(path) or not inside(target, out_dir):
            ctx.unread.append("a linked document of {} at a path the pre-check does not fetch".format(repo))
            return
        try:
            data = gh.raw("repos/{}/contents/{}?ref={}".format(repo, path, sha))
        except GitHubError:
            ctx.unread.append("the linked document {}/{} (it could not be read)".format(repo, path))
            return
        os.makedirs(os.path.dirname(target), exist_ok=True)
        label = "document {}/{} at {}".format(repo, path, sha[:7])
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(ctx.quote(label, data, MAX_FILE_BYTES, linked=True))
        docs.append("{}/{}@{}".format(repo, path, sha[:7]))

    for repo in doc_repos:
        if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", repo) or repo.split("/")[0] != owner:
            continue
        seen = set()
        for m in re.finditer(r"https://github\.com/{}/(blob|tree)/([A-Za-z0-9._/-]+)".format(re.escape(repo)), text):
            if m.group(0) in seen:
                continue
            seen.add(m.group(0))
            kind, rest = m.group(1), m.group(2)
            if "/" not in rest:
                continue
            ref, path = rest.split("/", 1)
            try:
                sha = resolve_ref(gh, repo, ref, cache) if safe_relpath(ref) and safe_relpath(path) else None
            except GitHubError:
                ctx.unread.append("a linked document of {} (the repository could not be read)".format(repo))
                continue
            if not sha:
                ctx.unread.append("a linked document of {} outside its default branch, or at a path the pre-check "
                                  "does not fetch".format(repo))
                continue
            if kind == "blob":
                fetch(repo, sha, path)
                continue
            try:
                entries = gh.api("repos/{}/contents/{}?ref={}".format(repo, path, sha))
            except GitHubError:
                ctx.unread.append("the linked folder {}/{} (it could not be read)".format(repo, path))
                entries = []
            for entry in entries if isinstance(entries, list) else []:
                if entry.get("type") == "file" and re.search(r"\.(md|mdx|txt)$", entry.get("name", "")):
                    fetch(repo, sha, entry["path"])
    if skipped:
        ctx.unread.append("linked documents beyond the first {}, not read: {}".format(MAX_DOC_FILES, " ".join(skipped)))
    return docs


def applies(guide_path, changed):
    """A scoped guide (AGENTS.md, CLAUDE.md) applies to the files below its
    directory; one at the root applies to every file."""
    folder = guide_path.rpartition("/")[0]
    return not folder or any(p.startswith(folder + "/") for p in changed)


def collect_guide(gh, ctx, repo, base_sha, out_dir, changed):
    """The repository's guide at the base commit: every AGENTS.md and CLAUDE.md,
    then at most MAX_GUIDE_DOCS other documents. An AGENTS.md or CLAUDE.md that
    applies to a changed file (CHANGED: the paths of the pull request) but
    cannot be given to the reviewer - a path outside the plain character set,
    or a failed read - goes to cut_sources, so the result needs a person; any
    other guide document that cannot be read is a note."""
    tree = gh.api("repos/{}/git/trees/{}?recursive=1".format(repo, base_sha))
    if tree.get("truncated"):
        ctx.cut_sources.append("the file list of the base branch")
    guide, others, skipped = [], 0, 0
    for item in tree.get("tree", []):
        path = item.get("path", "")
        if item.get("type") != "blob" or not GUIDE.search(path):
            continue
        scoped = bool(SCOPED_GUIDE.search(path))
        if not safe_relpath(path):
            if scoped and applies(path, changed):
                ctx.cut_sources.append("an AGENTS.md or CLAUDE.md that applies to changed files, at a path with "
                                       "characters the pre-check does not fetch")
            continue
        if not scoped:
            if others >= MAX_GUIDE_DOCS:
                skipped += 1
                continue
            others += 1
        target = os.path.join(out_dir, path)
        if not inside(target, out_dir):
            continue
        try:
            data = gh.raw("repos/{}/contents/{}?ref={}".format(repo, path, base_sha))
        except GitHubError:
            if scoped and applies(path, changed):
                ctx.cut_sources.append("repository guide {} (it could not be read)".format(path))
            else:
                ctx.notes.append("The repository guide document {} could not be read.".format(path))
            continue
        if len(data) > MAX_FILE_BYTES:
            ctx.cut_sources.append("repository guide " + path)
            data = data[:MAX_FILE_BYTES]
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(data)
        guide.append(path)
    if skipped:
        ctx.notes.append("Only {} documents of the repository guide besides AGENTS.md and CLAUDE.md were read; {} more were not.".format(MAX_GUIDE_DOCS, skipped))
    return guide
