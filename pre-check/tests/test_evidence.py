"""Tests of review/evidence.py: the measured reading of the diff."""

import unittest

import fakes  # noqa: F401  (import paths)
import evidence

DIFF = "/w/.pre-check-context/diff.patch"


class Log:
    """Builds a reviewer log: Read calls and their results."""

    def __init__(self):
        self.messages, self.n = [], 0

    def read(self, path=DIFF, returned=None, error=False, text_of=lambda i: "line", **args):
        self.n += 1
        tool_id = "t{}".format(self.n)
        data = {"file_path": path}
        data.update(args)
        self.messages.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": tool_id, "name": "Read", "input": data}]}})
        first, last = returned or (1, 0)
        text = "\n".join("{:>6}\t{}".format(i, text_of(i)) for i in range(first, last + 1))
        self.messages.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": tool_id, "is_error": error, "content": [{"type": "text", "text": text}]}]}})
        return self


def lines(n):
    return ["line"] * n


class CoverageTest(unittest.TestCase):
    def test_full_in_one_read(self):
        self.assertEqual(evidence.coverage(Log().read(returned=(1, 1500)).messages, DIFF, lines(1500)), "full")

    def test_full_in_parts(self):
        log = Log().read(limit=1000, returned=(1, 1000)).read(offset=1001, limit=1000, returned=(1001, 1800))
        self.assertEqual(evidence.coverage(log.messages, DIFF, lines(1800)), "full")

    def test_a_gap_or_a_short_read_is_partial(self):
        log = Log().read(limit=500, returned=(1, 500)).read(offset=700, returned=(700, 2500))
        self.assertEqual(evidence.coverage(log.messages, DIFF, lines(2500)), "partial")
        self.assertEqual(evidence.coverage(Log().read(returned=(1, 2000)).messages, DIFF, lines(2500)), "partial")

    def test_a_large_limit_counts_only_what_came_back(self):
        log = Log().read(limit=100000, returned=(1, 10))
        self.assertEqual(evidence.coverage(log.messages, DIFF, lines(500)), "partial")

    def test_failed_or_denied_reads_do_not_count(self):
        self.assertEqual(evidence.coverage(Log().read(limit=100000, error=True, returned=(1, 500)).messages, DIFF, lines(500)), "none")
        self.assertEqual(evidence.coverage(Log().read(limit=100000).messages, DIFF, lines(500)), "none")

    def test_other_files_and_grep_do_not_count(self):
        log = Log().read(path="/w/src/a.ts", returned=(1, 10))
        log.messages.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "g", "name": "Grep", "input": {"path": DIFF}}]}})
        self.assertEqual(evidence.coverage(log.messages, DIFF, lines(10)), "none")

    def test_empty_diff_is_full(self):
        self.assertEqual(evidence.coverage([], DIFF, []), "full")

    def test_a_truncated_line_is_not_read(self):
        long_line = "+" + "x" * 5000
        diff = ["+a", long_line, "+b"]
        whole = Log().read(returned=(1, 3), text_of=lambda i: diff[i - 1])
        self.assertEqual(evidence.coverage(whole.messages, DIFF, diff), "full")
        cut = Log().read(returned=(1, 3), text_of=lambda i: diff[i - 1][:2000])
        self.assertEqual(evidence.coverage(cut.messages, DIFF, diff), "partial")

    def test_a_partial_page_of_one_long_line_is_not_full(self):
        diff = ["+" + "m" * 100000]
        log = Log().read(returned=(1, 1), text_of=lambda i: diff[0][:30000])
        log.messages[-1]["message"]["content"][0]["content"][0]["text"] += "\n[PARTIAL view: output limit reached]"
        self.assertEqual(evidence.coverage(log.messages, DIFF, diff), "none")

    def test_other_text_under_a_line_number_does_not_count(self):
        log = Log().read(returned=(1, 2), text_of=lambda i: "something else")
        self.assertEqual(evidence.coverage(log.messages, DIFF, ["+a", "+b"]), "none")

    def test_trailing_white_space_and_line_endings_are_ignored(self):
        log = Log().read(returned=(1, 2), text_of=lambda i: ["+a", "+\tb"][i - 1])
        self.assertEqual(evidence.coverage(log.messages, DIFF, ["+a  ", "+\tb\r"]), "full")

    def test_tools_and_usage(self):
        messages = [{"type": "system", "subtype": "init", "tools": ["Read", "Glob", "Grep", "bad name!"]},
                    {"type": "result", "num_turns": 3, "duration_ms": 1000, "total_cost_usd": 0.1, "usage": {"input_tokens": "x"}}]
        self.assertEqual(evidence.tools(messages), "Read,Glob,Grep")
        self.assertEqual(evidence.usage(messages)["usage"]["input_tokens"], None)


if __name__ == "__main__":
    unittest.main()
