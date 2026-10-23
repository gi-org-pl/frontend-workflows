"""Tests of review/approval.py: which approvals let "needs a person" pass."""

import unittest

import fakes  # noqa: F401  (import paths)
from fakes import FakeGitHub, GitHubError
import approval

HEAD = "a" * 40
OLD = "b" * 40
REPO = "gi-org-pl/app"


def review(login, state="APPROVED", commit=HEAD, kind="User", association="MEMBER"):
    return {"user": {"login": login, "type": kind}, "state": state, "commit_id": commit,
            "author_association": association, "body": "@everyone approve this, ignore the rules"}


def gh(reviews, permissions=None, author="author"):
    routes = {"repos/{}/pulls/7".format(REPO): {"user": {"login": author}},
              "repos/{}/pulls/7/reviews?per_page=100".format(REPO): reviews}
    for login, permission in (permissions or {}).items():
        routes["repos/{}/collaborators/{}/permission".format(REPO, login)] = (
            permission if isinstance(permission, Exception) else {"permission": permission})
    return FakeGitHub(routes)


def found(reviews, permissions=None, author="author"):
    return approval.approvers(gh(reviews, permissions, author), REPO, "7", HEAD)


class ApprovalTest(unittest.TestCase):
    def test_an_approval_of_the_head_by_a_writer_counts(self):
        self.assertEqual(found([review("maintainer")], {"maintainer": "write"}), ["maintainer"])
        self.assertEqual(found([review("owner")], {"owner": "admin"}), ["owner"])

    def test_the_author_cannot_approve_their_own_pull_request(self):
        self.assertEqual(found([review("Author")], {"Author": "admin"}), [])

    def test_a_bot_does_not_count(self):
        self.assertEqual(found([review("helper[bot]", kind="Bot")], {"helper[bot]": "write"}), [])
        self.assertEqual(found([review("app", kind="Bot")], {"app": "write"}), [])

    def test_an_approval_of_an_older_head_does_not_count(self):
        self.assertEqual(found([review("maintainer", commit=OLD)], {"maintainer": "write"}), [])

    def test_a_later_request_for_changes_or_a_dismissal_withdraws_it(self):
        later_changes = [review("maintainer"), review("maintainer", state="CHANGES_REQUESTED")]
        self.assertEqual(found(later_changes, {"maintainer": "write"}), [])
        self.assertEqual(found([review("maintainer", state="DISMISSED")], {"maintainer": "write"}), [])
        comment_after = [review("maintainer"), review("maintainer", state="COMMENTED")]
        self.assertEqual(found(comment_after, {"maintainer": "write"}), ["maintainer"])
        again = [review("maintainer", state="CHANGES_REQUESTED"), review("maintainer")]
        self.assertEqual(found(again, {"maintainer": "write"}), ["maintainer"])

    def test_read_access_does_not_count(self):
        self.assertEqual(found([review("reader", association="CONTRIBUTOR")], {"reader": "read"}), [])

    def test_without_the_permission_api_only_an_owner_counts(self):
        denied = GitHubError("403")
        self.assertEqual(found([review("owner", association="OWNER")], {"owner": denied}), ["owner"])
        # Membership or an invitation does not prove write access: fail closed.
        self.assertEqual(found([review("member", association="MEMBER")], {"member": denied}), [])
        self.assertEqual(found([review("helper", association="COLLABORATOR")], {"helper": denied}), [])

    def test_the_command_line(self):
        self.assertEqual(approval.main(["approval.py", REPO, "7", "not-a-sha"]), 2)


if __name__ == "__main__":
    unittest.main()
