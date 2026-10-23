#!/usr/bin/env python3
"""Whether a person approved the current head of a pull request.

A "needs a person" outcome passes the check where such an approval is the
gate. An approval counts when:

- it is the reviewer's latest decisive review (APPROVED, CHANGES_REQUESTED or
  DISMISSED; a COMMENTED review changes nothing), so a later request for
  changes or a dismissal withdraws it,
- it was given on the current head commit (its commit_id), so a push after it
  needs a new one,
- the reviewer is not the author of the pull request and not a bot,
- the reviewer can write to the repository: write, maintain or admin by the
  collaborator permission API; where that API cannot be read with the token,
  the review's author association OWNER, MEMBER or COLLABORATOR.

Nothing from the review body is read.

Usage: approval.py REPO PR_NUMBER HEAD_SHA
Exit 0 and print "approved" when such an approval exists, exit 1 otherwise.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "context"))

import github  # noqa: E402

DECISIVE = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}
WRITERS = {"admin", "maintain", "write"}
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


def is_bot(user):
    login = user.get("login") or ""
    return user.get("type") == "Bot" or login.endswith("[bot]")


def latest_decisions(reviews):
    """Each reviewer's latest decisive review, in the order GitHub gave them
    (the reviews API lists them chronologically)."""
    latest = {}
    for review in reviews:
        user = review.get("user") or {}
        login = user.get("login")
        if login and review.get("state") in DECISIVE:
            latest[login.lower()] = review
    return latest


def can_write(gh, repo, login, review):
    if not LOGIN.match(login):
        return False
    try:
        answer = gh.api("repos/{}/collaborators/{}/permission".format(repo, login)) or {}
    except github.GitHubError:
        return review.get("author_association") in TRUSTED
    return answer.get("permission") in WRITERS or answer.get("role_name") in WRITERS


def approvers(gh, repo, number, head):
    """The logins whose approval of HEAD counts."""
    pr = gh.api("repos/{}/pulls/{}".format(repo, number)) or {}
    author = ((pr.get("user") or {}).get("login") or "").lower()
    reviews = gh.api("repos/{}/pulls/{}/reviews?per_page=100".format(repo, number), paginate=True)
    found = []
    for login, review in latest_decisions(reviews).items():
        user = review.get("user") or {}
        if review.get("state") != "APPROVED" or review.get("commit_id") != head:
            continue
        if login == author or is_bot(user):
            continue
        if can_write(gh, repo, user.get("login", ""), review):
            found.append(login)
    return sorted(found)


def main(argv):
    if len(argv) != 4 or not re.match(r"^[0-9a-f]{40}$", argv[3]) or not argv[2].isdigit():
        print(__doc__, file=sys.stderr)
        return 2
    try:
        found = approvers(github, argv[1], argv[2], argv[3])
    except (github.GitHubError, ValueError):
        return 1
    if not found:
        return 1
    print("approved")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
