"""Contract -> vision reviewer -> pixel audit, with a stub `codex` so no model is called."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins/image-studio/skills"
AUDIT = SKILLS / "image-verify/scripts/audit_candidate.py"
CONVERT = SKILLS / "image-verify/scripts/contract_to_brief.py"
REVIEW = SKILLS / "image-loop/scripts/review.py"
BRIEF_SCHEMA = SKILLS / "image-loop/references/brief.schema.json"

STUB_CODEX = """#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
open(args[args.index('-o') + 1], 'w').write(os.environ['STUB_REPORT'])
print('{"type":"turn.completed","usage":{"input_tokens":1}}')
"""


def run(*cmd, env=None):
    return subprocess.run([sys.executable, *map(str, cmd)], capture_output=True, text=True, env=env)


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        Image.new("RGB", (100, 100), "white").save(self.dir / "source.png")
        candidate = Image.new("RGB", (100, 100), "white")
        ImageDraw.Draw(candidate).rectangle((15, 15, 35, 35), fill="blue")
        candidate.save(self.dir / "candidate.png")
        mask = Image.new("L", (100, 100), 0)
        ImageDraw.Draw(mask).rectangle((5, 5, 45, 45), fill=255)
        mask.save(self.dir / "mask.png")
        self.contract = self.dir / "contract.json"
        self.contract.write_text(json.dumps({
            "version": 1, "mode": "repair", "intent": "Recolor the square blue",
            "canvas": {"width": 100, "height": 100, "format": "PNG"},
            "targets": [{"id": "A:#1", "name": "square", "bbox": [10, 10, 31, 31]},
                        {"id": "A:#2", "name": "corner mark", "bbox": [60, 60, 20, 20]}],
            "checks": [{"id": "C1", "target_id": "A:#1", "kind": "change", "requirement": "Square is blue"},
                       {"id": "K1", "target_id": "A:#2", "kind": "keep", "requirement": "Corner mark unchanged"}],
            "pixel_lock_outside_mask": True, "max_repairs": 3}))

    def tearDown(self):
        self.tmp.cleanup()

    def report(self, c1="pass"):
        return {"criteria": [
            {"id": "C1", "status": c1, "evidence": "Square interior looks blue" if c1 == "pass" else "Square is still white",
             "suggested_fix": "" if c1 == "pass" else "Fill the square with muted blue"},
            {"id": "K1", "status": "pass", "evidence": "Corner mark matches the source", "suggested_fix": ""}],
            "summary": "stub"}

    def audit(self, review, out="audit"):
        return run(AUDIT, "--contract", self.contract, "--source", self.dir / "source.png",
                   "--candidate", self.dir / "candidate.png", "--mask", self.dir / "mask.png",
                   "--review", review, "--out", self.dir / out)

    def test_brief_matches_image_loop_schema(self):
        from jsonschema import Draft202012Validator
        result = run(CONVERT, self.contract, "--out", self.dir / "brief.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        brief = json.loads((self.dir / "brief.json").read_text())
        Draft202012Validator(json.loads(BRIEF_SCHEMA.read_text())).validate(brief)
        self.assertEqual([c["kind"] for c in brief["criteria"]], ["requested", "protected"])
        self.assertIn("x=10 y=10 w=31 h=31", brief["criteria"][0]["target"])

    def test_audit_accepts_reviewer_report_format(self):
        path = self.dir / "report.json"
        path.write_text(json.dumps(self.report()))
        result = self.audit(path)
        self.assertEqual(json.loads(result.stdout)["action"], "accepted_by_checks", result.stderr)

    def test_repair_prompt_names_source_boxes_and_fix(self):
        path = self.dir / "report.json"
        path.write_text(json.dumps(self.report(c1="fail")))
        result = self.audit(path)
        self.assertEqual(json.loads(result.stdout)["action"], "repair", result.stderr)
        prompt = (self.dir / "audit/repair-prompt.txt").read_text()
        self.assertIn("C1: Square is blue (square (A:#1) at source box x=10, y=10, width=31, height=31)", prompt)
        self.assertIn("Suggested minimal fix: Fill the square with muted blue", prompt)
        self.assertIn("K1: Corner mark unchanged", prompt)
        self.assertIn("restored from the source", prompt)

    def test_full_pipeline_with_stub_reviewer(self):
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "codex"
        stub.write_text(STUB_CODEX)
        stub.chmod(0o755)
        env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                   STUB_REPORT=json.dumps(self.report()))
        self.assertEqual(run(CONVERT, self.contract, "--out", self.dir / "brief.json").returncode, 0)
        review = run(REVIEW, "--brief", self.dir / "brief.json", "--source", self.dir / "source.png",
                     "--candidate", self.dir / "candidate.png", "--out", self.dir / "vision",
                     "--model", "stub-model", env=env)
        self.assertEqual(json.loads(review.stdout)["action"], "accepted_by_checks", review.stderr)
        audit = self.audit(self.dir / "vision/report.json")
        self.assertEqual(json.loads(audit.stdout)["action"], "accepted_by_checks", audit.stderr)

    def loop_review(self, report, out):
        path = self.dir / f"{out}.json"
        path.write_text(json.dumps(report))
        run(CONVERT, self.contract, "--out", self.dir / "brief.json") if not (self.dir / "brief.json").exists() else None
        return run(REVIEW, "--brief", self.dir / "brief.json", "--source", self.dir / "source.png",
                   "--candidate", self.dir / "candidate.png", "--out", self.dir / out, "--report", path)

    def test_image_loop_decides_from_external_report_without_codex(self):
        env_path = os.environ["PATH"]
        result = self.loop_review(self.report(c1="fail"), "external")
        self.assertEqual(os.environ["PATH"], env_path)
        self.assertEqual(json.loads(result.stdout)["action"], "repair", result.stderr)
        run_record = json.loads((self.dir / "external/run.json").read_text())
        self.assertEqual(run_record["adapter"], "external report")
        self.assertTrue((self.dir / "external/repair-prompt.txt").exists())

    def test_external_report_missing_an_id_is_invalid(self):
        report = self.report()
        report["criteria"].pop()
        self.loop_review(report, "partial")
        decision = json.loads((self.dir / "partial/decision.json").read_text())
        self.assertEqual(decision["action"], "stop_invalid_review")

    def test_model_and_report_are_mutually_exclusive(self):
        run(CONVERT, self.contract, "--out", self.dir / "brief.json")
        result = run(REVIEW, "--brief", self.dir / "brief.json", "--candidate", self.dir / "candidate.png",
                     "--source", self.dir / "source.png", "--out", self.dir / "both",
                     "--model", "m", "--report", self.dir / "brief.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not allowed with", result.stderr)

    def test_pixel_audit_overrules_a_wrong_vision_pass(self):
        leak = Image.open(self.dir / "candidate.png")
        leak.putpixel((95, 95), (0, 0, 0))
        leak.save(self.dir / "candidate.png")
        path = self.dir / "report.json"
        path.write_text(json.dumps(self.report()))
        result = self.audit(path)
        self.assertEqual(json.loads(result.stdout)["action"], "reject_technical")


if __name__ == "__main__":
    unittest.main()
