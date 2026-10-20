import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bench/score.py"
TRUTH = {"image": "i.png", "size": [1000, 1000], "defects": [
    {"id": "D1", "box": [100, 100, 200, 200], "kind": "hand"},
    {"id": "D2", "box": [500, 500, 600, 700], "kind": "text"},
    {"id": "D3", "box": [800, 50, 900, 150], "kind": "hand"}]}
TABLE = """| No. | Box x0,y0,x1,y1 (image pixels) | Problem | Severity (high / medium / low) | Fix |
| --- | --- | --- | --- | --- |
| 1 | 120,110,190,210 | six fingers | high | redraw |
| 2 | 540,520,560,560 | garbled word | medium | retype |
| 3 | 300,300,320,320 | nothing there | low | - |
"""


class BenchScoreTests(unittest.TestCase):
    def run_score(self, truth, found, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            t, f = Path(tmp) / "truth.json", Path(tmp) / "found.md"
            t.write_text(truth if isinstance(truth, str) else json.dumps(truth))
            f.write_text(found)
            return subprocess.run([sys.executable, str(SCRIPT), "--truth", str(t), "--found", str(f)] + list(extra),
                                  capture_output=True, text=True)

    def test_hunter_table_is_scored(self):
        r = self.run_score(TRUTH, TABLE, "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = json.loads(r.stdout)
        self.assertEqual((s["found_true"], s["true_defects"], s["found_boxes"]), (2, 3, 3))
        self.assertEqual(s["missed"], ["D3 (hand)"])
        self.assertEqual(s["by_kind"], {"hand": "1/2", "text": "1/1"})
        self.assertAlmostEqual(s["precision"], 0.667, places=3)

    def test_two_boxes_on_one_defect_count_it_once(self):
        found = json.dumps([{"box": [100, 100, 200, 200]}, {"box": [110, 110, 190, 190]}])
        s = json.loads(self.run_score(TRUTH, found, "--json").stdout)
        self.assertEqual(s["found_true"], 1)
        self.assertEqual(s["precision"], 0.5)  # the duplicate box points at nothing new

    def test_whole_image_rows_duplicates_and_backticks(self):
        table = TABLE.splitlines()[:2] + [
            "| 1 | whole image | soft overall | low | sharpen |",
            "| 2 | 0,0,1000,1000 | color cast | low | grade |",
            "| 3 | `120,110,190,210` | six fingers | high | redraw |",
            "| 4 | 120,110,190,210 | six fingers again | high | redraw |"]
        s = json.loads(self.run_score(TRUTH, "\n".join(table), "--json").stdout)
        self.assertEqual((s["found_true"], s["found_boxes"]), (1, 4))
        self.assertEqual(s["precision"], 0.25)

    def test_one_box_cannot_claim_two_defects(self):
        truth = {"size": [1000, 1000], "defects": [
            {"id": "A", "box": [0, 0, 100, 100], "kind": "hand"}, {"id": "B", "box": [50, 50, 150, 150], "kind": "hand"}]}
        found = json.dumps([{"box": [40, 40, 110, 110]}])
        s = json.loads(self.run_score(truth, found, "--json").stdout)
        self.assertEqual(s["found_true"], 1)

    def test_bad_input_exits_2(self):
        self.assertEqual(self.run_score("{}", TABLE).returncode, 2)
        bad = {"defects": [{"id": "D1", "box": [5, 5, 5, 9], "kind": "hand"}]}
        r = self.run_score(bad, TABLE)
        self.assertEqual(r.returncode, 2)
        self.assertIn("no area", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
