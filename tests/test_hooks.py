"""The repo's Claude Code hooks (.claude/hooks/guard.py)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / ".claude/hooks/guard.py"


def hook(mode, payload):
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(GUARD), mode], input=data, capture_output=True, text=True,
                          env=dict(os.environ, CLAUDE_PROJECT_DIR=str(ROOT)))


class GuardTests(unittest.TestCase):
    def asks(self, path):
        run = hook("pre", {"tool_input": {"file_path": path}})
        self.assertEqual(run.returncode, 0, run.stderr)
        return bool(run.stdout.strip()) and json.loads(run.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"

    def test_attribution_files_ask_in_any_spelling(self):
        for path in (ROOT / "LICENSE", ROOT / "NOTICE", "NOTICE", ROOT / "license", ROOT / "Notice"):
            self.assertTrue(self.asks(str(path)), path)
        for path in (ROOT / "README.md", ROOT / "plugins/LICENSE"):
            self.assertFalse(self.asks(str(path)), path)

    def test_bad_hook_input_is_not_a_traceback(self):
        for mode, data in (("pre", "not json"), ("post", "[]"), ("pre", "{}")):
            run = hook(mode, data)
            self.assertNotIn("Traceback", run.stderr, (mode, data))

    def test_post_hook_reports_python_3_9_syntax_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.py"
            bad.write_text("match x:\n    case 1:\n        pass\n")
            run = hook("post", {"tool_input": {"file_path": str(bad)}})
            if "no Python 3.9 found" in run.stderr:
                self.skipTest("no Python 3.9 interpreter on this machine")
            self.assertEqual(run.returncode, 2, run.stderr)


if __name__ == "__main__":
    unittest.main()
