"""Tests of review/render.py: presentation only - every finding with its body,
plain-text escaping, allowlisted links, and that display limits do not touch
the outcome."""

import copy
import os
import re
import sys
import unittest
from unittest import mock

import fakes  # noqa: F401  (import paths)
import render
import typical
from test_evaluate import finding, outcome, result, scope

SNAPSHOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots", "typical-comment.txt")


def typical_comment(res=None, sc=None, coverage="full"):
    res, sc = res or copy.deepcopy(typical.RESULT), sc or copy.deepcopy(typical.SCOPE)
    with mock.patch.dict(os.environ, typical.ENV):
        return render.render(res, sc, outcome(res, sc, coverage), coverage)


def rendered(res, sc=None):
    sc = sc or scope()
    return render.render(res, sc, outcome(res, sc), "full")


class PublicationTest(unittest.TestCase):
    def test_every_body_is_in_the_main_comment(self):
        findings = [finding("blocking", title="no line", body="evidence one"),
                    finding("blocking", title="outside hunk", body="evidence two", inline=True, line=99),
                    finding(title="inline ok", body="evidence three", inline=True, line=3)]
        comment, inline = rendered(result(findings))
        for text in ["evidence one", "evidence two", "evidence three"]:
            self.assertIn(text, comment)
        self.assertEqual(len(inline), 1)

    def test_more_than_fifteen_inline_findings_keep_their_bodies(self):
        findings = [finding(title="t{}".format(i), body="body{}".format(i), inline=True, line=2) for i in range(20)]
        comment, inline = rendered(result(findings))
        self.assertEqual(len(inline), 15)
        for i in range(20):
            self.assertIn("body{}".format(i), comment)

    def test_display_cap_shows_blockers_and_keeps_the_outcome(self):
        findings = [finding(title="a{}".format(i)) for i in range(30)] + [finding("blocking", title="the blocker")]
        comment, _ = rendered(result(findings))
        self.assertIn("the blocker", comment)
        self.assertIn("## Pre-check: ❌ changes needed · 1 blocking, 30 minor findings", comment)
        self.assertIn("31 findings were returned", comment)

    def test_identical_titles_at_two_lines_stay_distinct(self):
        findings = [finding(title="same", inline=True, line=2), finding(title="same", inline=True, line=4)]
        _, inline = rendered(result(findings))
        self.assertEqual(len({i["fingerprint"] for i in inline}), 2)

    def test_advisory_is_not_called_no_findings(self):
        comment, _ = rendered(result([finding()]))
        self.assertIn("## Pre-check: ✅ passed · 1 minor finding\n", comment)
        self.assertNotIn("no findings", comment)


class AllowedLinkTest(unittest.TestCase):
    def test_legit_links_pass(self):
        for url in ["https://github.com/gi-org-pl/repo/blob/main/x.md#L10",
                    "https://github.com/gi-org-pl/mypolitics-app/actions/runs/123",
                    "https://www.figma.com/design/KEY/name?node-id=1-2",
                    "https://figma.com/design/KEY/name?node-id=1-2",
                    "https://gi.org.pl/path"]:
            self.assertTrue(render.allowed_link(url), url)

    def test_traversal_and_tricks_are_rejected(self):
        for url in ["https://github.com/gi-org-pl/../other-org/repo",
                    "https://github.com/gi-org-pl/%2e%2e/other-org/repo",
                    "https://github.com/gi-org-pl/.%2e/other-org/repo",
                    "https://github.com/gi-org-pl/%2e./other-org/repo",
                    "https://github.com/gi-org-pl/..%2fother-org/repo",
                    "https://github.com/gi-org-pl/%252e%252e/other-org/repo",
                    "https://github.com/gi-org-pl/%2E%2E/other-org/repo",
                    "https://github.com/gi-org-pl/x%5c..%5cevil",
                    "https://github.com/gi-org-pl//evil",
                    "https://github.com/evil-org/repo",
                    "https://github.com.evil.example/gi-org-pl/",
                    "http://github.com/gi-org-pl/repo",
                    "https://figma.com.evil.example/x"]:
            self.assertFalse(render.allowed_link(url), url)


class EscapeTest(unittest.TestCase):
    def assert_no_link(self, text):
        out = render.multi_line(text, 3000)
        self.assertNotRegex(out, r"(?<!\\)\[[^\]]*(?<!\\)\]\(", out)
        self.assertNotRegex(out, r"(?m)^\s*(?<!\\)\[[^\]]+(?<!\\)\]:", out)
        self.assertNotRegex(out, r"(?i)https?://", out)
        self.assertNotRegex(out, r"(?i)\bwww\.", out)
        self.assertNotIn("<", out)

    def test_no_model_link_survives(self):
        for text in ["[x](https://evil.example)", "[Review][evidence]\n\n[evidence]: //attacker.example/collect",
                     "[shortcut]\n\n[shortcut]: https://evil.example", "<https://evil.example>",
                     "https://evil.example/raw", "www.evil.example", "see //attacker.example/x",
                     "[x](https://github.com/gi-org-pl/../evil)", "%68ttps://evil.example"]:
            self.assert_no_link(text)

    def test_mentions_html_images(self):
        out = render.one_line("@team <b>x</b> ![i](https://evil.example/p.png) a@b.example", 400)
        for bad in ["@team", "<b>", "![", "a@b"]:
            self.assertNotIn(bad, out)

    def test_no_markdown_structure_from_the_model(self):
        out = render.multi_line("# heading\n- item\n> quote\n| a | b |\n**Result:** passed", 3000)
        for line in out.split("\n"):
            self.assertFalse(line.startswith(("#", "- ", ">", "|", "**")), line)

    def test_suggestion_fence_becomes_plain_code(self):
        out = render.multi_line("x\n```suggestion\ncode\n```", 3000)
        self.assertNotIn("suggestion", out)
        self.assertIn("```\ncode\n```", out)

    def test_code_stays_literal(self):
        self.assertIn("`a < b`", render.one_line("see `a < b` here", 400))

    def test_tokens_are_redacted(self):
        self.assertNotIn("sk-ant-oat01", render.one_line("sk-ant-oat01-" + "A" * 40, 400))


class UnreadContextTest(unittest.TestCase):
    def test_unread_context_is_listed_and_the_result_says_why_it_is_not_clean(self):
        sc = scope(unread_context=["the linked document gi-org-pl/product/a.md (it could not be read)"])
        comment, _ = render.render(result(), sc, outcome(result(), sc), "full")
        self.assertIn("## Pre-check: ✅ passed · no findings", comment)
        self.assertIn("Not clean: some linked context was not read in full", comment)
        self.assertIn("Linked context not read in full (does not need a person by itself)", comment)
        self.assertIn(r"gi\-org\-pl/product/a\.md", comment)


def visible(comment):
    """What a reader sees before opening anything: the comment without its
    folded blocks and hidden markers."""
    folded = re.sub(r"(?s)<details>.*?</details>", "", comment)
    return re.sub(r"<!--.*?-->", "", folded)


class CompactCommentTest(unittest.TestCase):
    def test_typical_result_matches_the_snapshot(self):
        comment, _ = typical_comment()
        with open(SNAPSHOT, encoding="utf-8") as fh:
            self.assertEqual(comment, fh.read())

    def test_typical_result_is_short_before_the_folds(self):
        comment, _ = typical_comment()
        self.assertLess(len(visible(comment)), 3000)
        self.assertIn("## Pre-check: ✅ passed · 3 minor findings", comment)
        self.assertEqual(comment.count("<details>"), 4)  # findings, decisions, scope, excluded files

    def test_where_links_are_built_from_the_scope(self):
        comment, _ = typical_comment()
        self.assertIn("[authClient\\.ts\\:4](https://github.com/gi-org-pl/mypolitics-app/blob/{}/"
                      "src/services/auth/client/authClient.ts#L4)".format(typical.HEAD), comment)
        res = copy.deepcopy(typical.RESULT)
        res["findings"][0]["path"] = "https://evil.example/x.ts"
        comment, _ = typical_comment(res)
        # A path that is not a changed file is shown as code (never a link).
        self.assertIn("| `x.ts:4` |", comment)
        self.assertNotIn("](https://evil", comment)

    def test_a_removed_line_of_a_renamed_file_links_to_its_old_name(self):
        res, sc = copy.deepcopy(typical.RESULT), copy.deepcopy(typical.SCOPE)
        sc["renamed"] = [{"from": "src/services/auth/client/oldClient.ts", "to": "src/services/auth/client/authClient.ts",
                          "status": "renamed"}]
        res["findings"][0]["side"] = "LEFT"
        comment, _ = typical_comment(res, sc)
        self.assertIn("/blob/{}/src/services/auth/client/oldClient.ts#L4)".format(typical.BASE), comment)

    def test_a_pipe_in_a_title_stays_in_its_cell(self):
        for title in ["Union `a | b` and a | c", "Handle A | B", "Path `a\\|b` or c\\|d", "Even `a\\\\|b` run"]:
            res = copy.deepcopy(typical.RESULT)
            res["findings"][0]["title"] = title
            comment, _ = typical_comment(res)
            row = next(line for line in comment.split("\n") if line.startswith("| 🟡 | " + title[:4]))
            # A cell boundary is a pipe after an even number of backslashes.
            boundaries = re.findall(r"(?<!\\)(?:\\\\)*\|", row)
            self.assertEqual(len(boundaries), 4, (title, row))

    def test_needs_a_person_headline_and_status(self):
        sc = copy.deepcopy(typical.SCOPE)
        sc["workflow_changes"] = [".github/workflows/ci.yml"]
        sc["human_paths"] = [{"path": ".github/workflows/ci.yml", "reason": "CI workflow"}]
        comment, _ = typical_comment(sc=sc)
        self.assertIn("## Pre-check: ⚠️ needs a person (it changes CI workflows) · 3 minor findings", comment)
        self.assertIn("The check fails: the base branch does not require an approval of the current head", comment)
        with mock.patch.dict(os.environ, {"APPROVAL_GATE": "current-head"}):
            comment, _ = typical_comment(sc=sc)
        self.assertIn("The check passes: a person's review and approval of this commit is the gate", comment)

    def test_changes_headline(self):
        res = copy.deepcopy(typical.RESULT)
        res["findings"][0]["severity"] = "blocking"
        comment, _ = typical_comment(res)
        self.assertIn("## Pre-check: ❌ changes needed · 1 blocking, 2 minor findings", comment)
        self.assertIn("| 🔴 | The stand", comment)

    def test_more_than_five_decisions_are_folded(self):
        res = copy.deepcopy(typical.RESULT)
        res["decisions"]["new_dependencies"] = [typical.decision("dep{}".format(i), "added.", "low") for i in range(3)]
        comment, _ = typical_comment(res)
        top = comment.split("**Decisions to look at**")[1].split("**For QA**")[0]
        self.assertEqual(top.count("\n- **"), 5)
        self.assertTrue(top.strip().startswith("- **Session state**"))  # high first, in category order
        self.assertIn("<summary>All technical decisions (10)</summary>", comment)
        self.assertIn("dep2", comment.split("All technical decisions")[1])

    def test_qa_steps_are_capped_for_display(self):
        res = copy.deepcopy(typical.RESULT)
        res["qa"] = ["step {}".format(i) for i in range(8)]
        comment, _ = typical_comment(res)
        self.assertIn("5. step 4", comment)
        self.assertNotIn("6. step 5", comment)


if __name__ == "__main__":
    if "--update" in sys.argv:
        os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
        with open(SNAPSHOT, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(typical_comment()[0])
        print("Updated " + SNAPSHOT)
    else:
        unittest.main()
