"""Regression tests for review.py input, encoding and decode hazards (uses a stub `codex`; the real one is never run)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from deps import needs_jsonschema, needs_pillow  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "plugins/image-studio/skills/image-loop/scripts/review.py"
C_LOCALE = {"LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONCOERCE_CLOCALE": "0"}
STUB_CODEX = """#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
sys.stdout.buffer.write(os.environb.get(b'STUB_STDOUT', b''))
if os.environ.get('STUB_REPORT_FILE'):
    open(args[args.index('-o') + 1], 'wb').write(open(os.environ['STUB_REPORT_FILE'], 'rb').read())
sys.exit(int(os.environ.get('STUB_RC', '0')))
"""


def report(status="pass", evidence="Visible evidence.", fix=""):
    return {"criteria": [{"id": "C1", "status": status, "evidence": evidence, "suggested_fix": fix}], "summary": "ok"}


@needs_pillow
@needs_jsonschema
class ReviewFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        Image.new("RGB", (8, 8), "white").save(self.dir / "c.png")
        self.brief = {"name": "t", "intent": "Make it blue.", "criteria": [
            {"id": "C1", "target": "square", "kind": "requested", "requirement": "Square is blue."}],
            "file_checks": {"width": 8, "height": 8, "format": "PNG", "alpha_required": False}}

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, value, encoding="utf-8"):
        path = self.dir / name
        path.write_bytes((value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)).encode(encoding))
        return path

    def review(self, *extra, brief=None, candidate="c.png", out="out", env=None, brief_encoding="utf-8"):
        brief_path = self.put("brief.json", self.brief if brief is None else brief, brief_encoding)
        return subprocess.run([sys.executable, str(REVIEW), "--brief", str(brief_path), "--candidate",
                               str(self.dir / candidate), "--out", str(self.dir / out), *map(str, extra)],
                              capture_output=True, text=True, env=dict(os.environ, **(env or {})))

    def decision(self, out="out"):
        return json.loads((self.dir / out / "decision.json").read_text(encoding="utf-8"))

    def stub_env(self, **extra):
        bin_dir = self.dir / "bin"
        bin_dir.mkdir(exist_ok=True)
        stub = bin_dir / "codex"
        stub.write_text(STUB_CODEX)
        stub.chmod(0o755)
        return dict(PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", **extra)

    def assertClean(self, result, code=2):
        self.assertEqual(result.returncode, code, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    # 1. encoding
    def test_non_ascii_evidence_survives_a_non_utf8_locale(self):
        rep = self.put("r.json", report("fail", "màu đỏ 手", "tô lại màu xanh 手"))
        result = self.review("--report", rep, env=C_LOCALE)
        self.assertClean(result, 0)
        self.assertEqual(self.decision()["action"], "repair")
        self.assertIn("手", (self.dir / "out/repair-prompt.txt").read_text(encoding="utf-8"))
        self.assertIn("màu đỏ 手", (self.dir / "out/report.json").read_text(encoding="utf-8"))

    def test_bom_json_is_accepted(self):
        rep = self.put("r.json", report(), "utf-8-sig")
        result = self.review("--report", rep, brief_encoding="utf-8-sig")
        self.assertClean(result, 0)
        self.assertEqual(self.decision()["action"], "accepted_by_checks")

    # 2. non-UTF-8 reviewer output
    def test_non_utf8_reviewer_stdout_ends_in_a_documented_decision(self):
        env = self.stub_env(STUB_STDOUT="\udcff\udcfe garbage\n", STUB_RC="1")
        result = self.review("--model", "stub", env=env)
        self.assertClean(result)
        self.assertEqual(self.decision()["action"], "stop_provider")
        self.assertTrue((self.dir / "out/run.json").exists())

    def test_non_utf8_reviewer_report_is_an_invalid_review(self):
        self.put("bad.bin", "x")
        (self.dir / "bad.bin").write_bytes(b'{"criteria": "\xff\xfe"}')
        env = self.stub_env(STUB_STDOUT="\udcff\n", STUB_REPORT_FILE=str(self.dir / "bad.bin"))
        result = self.review("--model", "stub", env=env)
        self.assertClean(result)
        self.assertEqual(self.decision()["action"], "stop_invalid_review")
        self.assertTrue((self.dir / "out/run.json").exists())

    # 3. output directory errors
    def test_unusable_output_directory_is_a_clean_error(self):
        rep = self.put("r.json", report())
        (self.dir / "afile").write_text("x")
        (self.dir / "ro").mkdir()
        (self.dir / "ro").chmod(0o555)
        try:
            for out in ("afile/sub", "x" * 300 + "/o", "ro/o" if os.geteuid() else "afile/o"):
                result = self.review("--report", rep, out=out)
                self.assertClean(result)
                self.assertIn("output directory", result.stderr.lower(), out)
        finally:
            (self.dir / "ro").chmod(0o755)

    # 4. missing Pillow
    def test_missing_pillow_is_a_clean_error(self):
        block = self.dir / "blocker/PIL"
        block.mkdir(parents=True)
        (block / "__init__.py").write_text("raise ModuleNotFoundError(\"No module named 'PIL'\")\n")
        rep = self.put("r.json", report())
        result = self.review("--report", rep, env={"PYTHONPATH": str(self.dir / "blocker")})
        self.assertClean(result)
        self.assertIn("pillow", result.stderr.lower())

    # 5. decode hazards
    def test_decompression_bomb_candidate_is_clean(self):
        Image.new("1", (14000, 14000)).save(self.dir / "bomb.png")
        result = self.review("--report", self.put("r.json", report()), candidate="bomb.png")
        self.assertClean(result, 2)

    def test_animated_candidates_are_rejected_technical(self):
        frames = [Image.new("RGB", (8, 8), c) for c in ("white", "black")]
        for name, fmt in (("a.gif", "GIF"), ("a.webp", "WEBP"), ("a.png", "PNG")):
            frames[0].save(self.dir / name, save_all=True, append_images=frames[1:], duration=50, loop=0)
            self.brief["file_checks"]["format"] = fmt
            result = self.review("--report", self.put("r.json", report()), candidate=name, out=f"out-{name}")
            self.assertClean(result, 0)
            decision = self.decision(f"out-{name}")
            self.assertEqual(decision["action"], "reject_technical", name)
            self.assertIn("animated images are not supported", " ".join(decision["issues"]))

    # 6. malformed JSON
    def test_deeply_nested_json_is_clean(self):
        deep = "[" * 100000 + "]" * 100000
        result = self.review("--report", self.put("r.json", report()), brief=deep)
        self.assertClean(result)
        self.assertFalse((self.dir / "out").exists())
        result = self.review("--report", self.put("deep.json", deep))
        self.assertClean(result)
        self.assertEqual(self.decision()["action"], "stop_invalid_review")

    def test_lone_surrogate_report_is_an_invalid_review(self):
        rep = self.put("r.json", '{"criteria":[{"id":"C1","status":"pass","evidence":"bad \\ud800","suggested_fix":""}],"summary":"s"}')
        result = self.review("--report", rep)
        self.assertClean(result)
        self.assertEqual(self.decision()["action"], "stop_invalid_review")
        self.assertEqual(sorted(p.name for p in (self.dir / "out").iterdir()), ["decision.json"])

    def test_lone_surrogate_brief_is_a_clean_error_without_output(self):
        self.brief["intent"] = "bad \ud800"
        result = self.review("--report", self.put("r.json", report()), brief=json.dumps(self.brief))  # ascii-escaped
        self.assertClean(result)
        self.assertFalse((self.dir / "out").exists())

    # 7. repair limit message
    def test_changed_repair_limit_is_named(self):
        self.brief["max_repairs"] = 3
        rep = self.put("r.json", report("fail", "still white", "paint it"))
        self.assertClean(self.review("--report", rep, out="r0"), 0)
        self.brief["max_repairs"] = 4
        result = self.review("--report", rep, "--previous", self.dir / "r0", out="r1")
        self.assertEqual(result.returncode, 2)
        self.assertIn("different repair limit", result.stderr)
        self.brief["max_repairs"] = 3
        self.brief["intent"] = "Something else"
        result = self.review("--report", rep, "--previous", self.dir / "r0", out="r2")
        self.assertIn("different brief", result.stderr)

    # 8. any Pillow format name
    def test_brief_format_accepts_any_pillow_format_name(self):
        Image.new("RGB", (8, 8), "white").save(self.dir / "c.tiff")
        self.brief["file_checks"]["format"] = "TIFF"
        rep = self.put("r.json", report())
        result = self.review("--report", rep, candidate="c.tiff")
        self.assertClean(result, 0)
        self.assertEqual(self.decision()["action"], "accepted_by_checks")
        result = self.review("--report", rep, candidate="c.png", out="mismatch")
        self.assertClean(result, 0)
        self.assertEqual(self.decision("mismatch")["action"], "reject_technical")
        self.brief["file_checks"]["format"] = "png"
        self.assertEqual(self.review("--report", rep, out="lower").returncode, 2)

    # 9. IDs are compared exactly, as in audit_candidate.py
    def test_ids_with_surrounding_whitespace_are_refused(self):
        for bad in (" C1", "C1 ", "C1\n"):
            self.brief["criteria"][0]["id"] = bad
            result = self.review("--report", self.put("r.json", report()), out="ws")
            self.assertClean(result)
            self.assertIn("whitespace", result.stderr)
            self.assertFalse((self.dir / "ws").exists())

    # 10. --previous files that are valid JSON but not objects
    def test_previous_round_files_must_be_objects(self):
        rep = self.put("r.json", report("fail", "still white", "paint it"))
        self.assertClean(self.review("--report", rep, out="r0"), 0)
        for name, value in (("decision.json", "[]"), ("run.json", "[1]")):
            original = (self.dir / "r0" / name).read_text(encoding="utf-8")
            (self.dir / "r0" / name).write_text(value, encoding="utf-8")
            result = self.review("--report", rep, "--previous", self.dir / "r0", out="r1")
            self.assertClean(result)
            self.assertIn("JSON object", result.stderr)
            (self.dir / "r0" / name).write_text(original, encoding="utf-8")

    # 11. an invalid model report keeps the reason and prints the decision
    def test_invalid_model_report_records_the_reason(self):
        bad = self.put("bad.json", {"criteria": [{"id": "C1", "status": "pass", "evidence": "e", "suggested_fix": ""}]})
        result = self.review("--model", "stub", env=self.stub_env(STUB_REPORT_FILE=str(bad)))
        self.assertClean(result)
        decision = self.decision()
        self.assertEqual(decision["action"], "stop_invalid_review")
        self.assertIn("summary", decision["reason"])
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1]), decision)

    # 12. brief values that can never pass are refused before any output
    def test_brief_refuses_empty_values_and_jpg(self):
        rep = self.put("r.json", report())
        for field in ("id", "requirement"):
            brief = json.loads(json.dumps(self.brief))
            brief["criteria"][0][field] = ""
            result = self.review("--report", rep, brief=brief, out="empty-" + field)
            self.assertClean(result)
            self.assertFalse((self.dir / ("empty-" + field)).exists())
        self.brief["file_checks"]["format"] = "JPG"
        result = self.review("--report", rep, out="jpg")
        self.assertClean(result)
        self.assertIn("JPEG", result.stderr)

    # 13. a file failure with a supplied report does not mention reviewer usage
    def test_report_path_file_failure_message(self):
        self.brief["file_checks"]["width"] = 9
        self.assertClean(self.review("--report", self.put("r.json", report())), 0)
        self.assertEqual(self.decision()["action"], "reject_technical")
        self.assertNotIn("reviewer usage", self.decision()["reason"])

    # 14. the clean source must be a readable still image
    def test_unreadable_or_animated_source_is_refused(self):
        (self.dir / "text.png").write_text("not an image")
        frames = [Image.new("RGB", (8, 8), c) for c in ("white", "black")]
        frames[0].save(self.dir / "anim.gif", save_all=True, append_images=frames[1:], duration=50, loop=0)
        for name in ("text.png", "anim.gif"):
            result = self.review("--report", self.put("r.json", report()), "--source", self.dir / name, out="s-" + name)
            self.assertClean(result)
            self.assertIn("source", result.stderr.lower())
            self.assertFalse((self.dir / ("s-" + name)).exists())

    # 15. non-object JSON lines in the reviewer's stdout are ignored
    def test_non_object_stdout_lines_do_not_crash(self):
        good = self.put("good.json", report())
        env = self.stub_env(STUB_STDOUT='42\n"x"\n[1]\n', STUB_REPORT_FILE=str(good))
        result = self.review("--model", "stub", env=env)
        self.assertClean(result, 0)
        self.assertEqual(self.decision()["action"], "accepted_by_checks")
        self.assertTrue((self.dir / "out/run.json").exists())


if __name__ == "__main__":
    unittest.main()
