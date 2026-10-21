"""Tests of review/package.py: what leaves the analyse job as an artifact."""

import json
import os
import tempfile
import unittest

import fakes  # noqa: F401  (import paths)
import package


def run(result):
    messages = [{"type": "system", "subtype": "init"}]
    if result is not None:
        messages.append({"type": "result", "structured_output": result})
    with tempfile.TemporaryDirectory() as tmp:
        execution, scope, out = (os.path.join(tmp, n) for n in ("exec.json", "scope.json", "out"))
        with open(execution, "w", encoding="utf-8") as fh:
            json.dump(messages, fh)
        with open(scope, "w", encoding="utf-8") as fh:
            fh.write('{"head": "a"}')
        package.main(["package.py", execution, scope, out])
        files = sorted(os.listdir(out))
        packaged = None
        if "result.json" in files:
            with open(os.path.join(out, "result.json"), encoding="utf-8") as fh:
                packaged = json.load(fh)
    return files, packaged


class PackageTest(unittest.TestCase):
    def test_large_results_pass_whole(self):
        result = {"summary": "s", "findings": [{"body": "x" * 5000} for _ in range(40)]}
        files, packaged = run(result)
        self.assertEqual(files, ["result.json", "scope.json"])
        self.assertEqual(len(packaged["findings"]), 40)

    def test_credential_shapes_are_redacted(self):
        _, packaged = run({"summary": "key sk-ant-oat01-" + "A" * 40})
        self.assertNotIn("sk-ant-oat01", packaged["summary"])

    def test_a_leaking_result_is_withheld_whole(self):
        _, packaged = run({"summary": "s", "findings": [{"body": "password = hunter2hunter2x"}]})
        self.assertEqual(packaged, {"withheld": True})

    def test_no_result_writes_no_result_file(self):
        files, packaged = run(None)
        self.assertEqual((files, packaged), (["scope.json"], None))


if __name__ == "__main__":
    unittest.main()
