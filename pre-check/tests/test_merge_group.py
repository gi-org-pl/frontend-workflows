"""Tests of review/merge_group.py: which pull requests a merge queue entry contains."""

import unittest

import fakes  # noqa: F401  (import paths)
import merge_group


def queue(*entries):
    nodes = [{"position": p, "headCommit": {"oid": sha} if sha else None, "pullRequest": {"number": n}} for p, sha, n in entries]
    return {"data": {"repository": {"mergeQueue": {"entries": {"nodes": nodes}}}}}


REF = "refs/heads/gh-readonly-queue/main/pr-{}-abc{}"


class MembersTest(unittest.TestCase):
    def test_the_entries_ahead_belong_to_the_group(self):
        answer = queue((1, "abc1", 11), (2, "abc2", 12), (3, "abc3", 13))
        self.assertEqual(merge_group.members(answer, "abc2", REF.format(12, 2)), [11, 12])
        self.assertEqual(merge_group.members(answer, "abc1", REF.format(11, 1)), [11])

    def test_the_branch_must_name_the_entry_found(self):
        answer = queue((1, "abc1", 11), (2, "abc2", 12))
        self.assertIsNone(merge_group.members(answer, "abc2", REF.format(11, 2)))

    def test_an_unknown_head_or_a_broken_answer_is_not_a_membership(self):
        self.assertIsNone(merge_group.members(queue((1, "abc1", 11)), "fff", REF.format(11, 1)))
        self.assertIsNone(merge_group.members({"data": {"repository": {"mergeQueue": None}}}, "abc1", REF.format(11, 1)))
        self.assertIsNone(merge_group.members(queue((1, None, 11)), "abc1", REF.format(11, 1)))


if __name__ == "__main__":
    unittest.main()
