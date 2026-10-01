"""Regression tests for the QA audit findings (16-bit, RGBA masks, shared decisions, history, inputs)."""

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from deps import needs_jsonschema, needs_pillow

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - only the pixel tests need Pillow
    Image = ImageDraw = None

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins/image-studio/skills"
AUDIT = SKILLS / "image-verify/scripts/audit_candidate.py"
CONVERT = SKILLS / "image-verify/scripts/contract_to_brief.py"
REVIEW = SKILLS / "image-loop/scripts/review.py"


def load(name, path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load("audit_candidate", AUDIT)
controller = load("controller", SKILLS / "image-loop/scripts/controller.py")


def run(*cmd):
    return subprocess.run([sys.executable, *map(str, cmd)], capture_output=True, text=True)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def contract(self, mode="repair", keep=True, locked=True, max_repairs=3):
        checks = [{"id": "C1", "target_id": "A", "kind": "change", "requirement": "Left half changes"}]
        if keep:
            checks.append({"id": "K1", "target_id": "B", "kind": "keep", "requirement": "Right half stays"})
        data = {"version": 1, "mode": mode, "intent": "Change the left half",
                "canvas": {"width": 100, "height": 100, "format": "PNG"},
                "targets": [{"id": "A", "name": "left", "bbox": [0, 0, 50, 100]},
                            {"id": "B", "name": "right", "bbox": [50, 0, 50, 100]}],
                "checks": checks, "max_repairs": max_repairs}
        if locked:
            data["pixel_lock_outside_mask"] = True
        path = self.dir / "contract.json"
        path.write_text(json.dumps(data))
        return path

    def review(self, c1="pass", k1="pass", fmt="results"):
        items = [{"id": "C1", "status": c1, "evidence": "seen"}, {"id": "K1", "status": k1, "evidence": "seen"}]
        self.n += 1
        path = self.dir / f"review-{self.n}.json"
        body = {"results": items} if fmt == "results" else {
            "criteria": [dict(i, suggested_fix="") for i in items], "summary": "s"}
        path.write_text(json.dumps(body))
        return path

    def left_mask(self, mode="L"):
        if mode == "RGBA":
            mask = Image.new("RGBA", (100, 100), (255, 255, 255, 0))
            ImageDraw.Draw(mask).rectangle((0, 0, 49, 99), fill=(255, 255, 255, 255))
        else:
            mask = Image.new("L", (100, 100), 0)
            ImageDraw.Draw(mask).rectangle((0, 0, 49, 99), fill=255)
        path = self.dir / f"mask-{mode}.png"
        mask.save(path)
        return path

    def audit(self, source, candidate, review, mask=None, previous=None, repairs_used=None):
        self.n += 1
        out = self.dir / f"round-{self.n}"
        cmd = [AUDIT, "--contract", self.dir / "contract.json", "--candidate", candidate,
               "--review", review, "--out", out]
        if source:
            cmd += ["--source", source]
        if mask:
            cmd += ["--mask", mask]
        if previous:
            cmd += ["--previous", previous]
        if repairs_used is not None:
            cmd += ["--repairs-used", repairs_used]
        result = run(*cmd)
        return result, (json.loads(result.stdout) if result.returncode == 0 else None), out


@needs_pillow
class PixelTests(Case):
    def test_16bit_change_in_protected_half_is_caught(self):
        self.contract()
        Image.new("I;16", (100, 100), 1000).save(self.dir / "s.png")
        candidate = Image.new("I;16", (100, 100), 1000)
        draw = ImageDraw.Draw(candidate)
        draw.rectangle((0, 0, 49, 99), fill=0)
        draw.rectangle((50, 0, 99, 99), fill=50000)
        candidate.save(self.dir / "c.png")
        _, decision, out = self.audit(self.dir / "s.png", self.dir / "c.png", self.review(), self.left_mask())
        self.assertEqual(decision["action"], "reject_technical")
        self.assertEqual(json.loads((out / "evidence.json").read_text())["pixels"]["changed_by_target"]["B"], 5000)

    def test_16bit_change_above_255_counts_as_a_change(self):
        self.contract(keep=False, locked=False)
        Image.new("I;16", (100, 100), 1000).save(self.dir / "s.png")
        candidate = Image.new("I;16", (100, 100), 1000)
        ImageDraw.Draw(candidate).rectangle((0, 0, 49, 99), fill=2000)
        candidate.save(self.dir / "c.png")
        review = self.dir / "r.json"
        review.write_text(json.dumps({"results": [{"id": "C1", "status": "pass", "evidence": "seen"}]}))
        _, decision, _ = self.audit(self.dir / "s.png", self.dir / "c.png", review)
        self.assertEqual(decision["action"], "accepted_by_checks")

    def test_bit_depth_change_is_a_technical_issue(self):
        self.contract()
        Image.new("I;16", (100, 100), 1000).save(self.dir / "s.png")
        Image.new("RGB", (100, 100), "white").save(self.dir / "c.png")
        _, decision, _ = self.audit(self.dir / "s.png", self.dir / "c.png", self.review(), self.left_mask())
        self.assertIn("bit depth differ", " ".join(decision["issues"]))

    def test_transparent_area_of_rgba_mask_stays_locked(self):
        self.contract(keep=False)
        Image.new("RGB", (100, 100), "white").save(self.dir / "s.png")
        candidate = Image.new("RGB", (100, 100), "white")
        ImageDraw.Draw(candidate).rectangle((10, 10, 20, 20), fill="blue")
        candidate.putpixel((70, 70), (0, 0, 0))
        candidate.save(self.dir / "c.png")
        review = self.dir / "r.json"
        review.write_text(json.dumps({"results": [{"id": "C1", "status": "pass", "evidence": "seen"}]}))
        for mode in ("L", "RGBA"):
            _, decision, _ = self.audit(self.dir / "s.png", self.dir / "c.png", review, self.left_mask(mode))
            self.assertEqual(decision["action"], "reject_technical", mode)

    def test_exif_rotated_candidate_is_compared_as_displayed(self):
        self.contract(keep=False, locked=False)
        source = Image.new("RGB", (100, 100), "white")
        ImageDraw.Draw(source).rectangle((0, 0, 9, 9), fill="red")
        source.save(self.dir / "s.png")
        exif = Image.Exif()
        exif[0x0112] = 6  # displayed rotated 90 degrees
        source.save(self.dir / "c.png", exif=exif)
        review = self.dir / "r.json"
        review.write_text(json.dumps({"results": [{"id": "C1", "status": "fail", "evidence": "rotated"}]}))
        _, decision, out = self.audit(self.dir / "s.png", self.dir / "c.png", review)
        self.assertGreater(json.loads((out / "evidence.json").read_text())["pixels"]["changed_pixels"], 0)
        self.assertEqual(decision["action"], "repair")


class SharedDecisionTests(unittest.TestCase):
    """The loop controller and the audit decide the same way on the same verdicts."""

    def verdicts(self, c1, k1):
        return {"C1": {"id": "C1", "status": c1, "evidence": "e"}, "K1": {"id": "K1", "status": k1, "evidence": "e"}}

    def both(self, c1, k1, repairs_used=0, previous=None, max_repairs=3, file_ok=True):
        checks = {"C1": {"target_id": "A", "kind": "change"}, "K1": {"target_id": "B", "kind": "keep"}}
        results = self.verdicts(c1, k1)
        prev_results = self.verdicts(*previous) if previous else None
        audit_decision = audit.decide(checks, results, [] if file_ok else ["bad size"], repairs_used, max_repairs, prev_results)
        brief = {"intent": "i", "file_checks": {}, "criteria": [
            {"id": "C1", "target": "a", "kind": "requested", "requirement": "r"},
            {"id": "K1", "target": "b", "kind": "protected", "requirement": "r"}]}
        report = {"criteria": [dict(v, suggested_fix="") for v in results.values()], "summary": "s"}
        prev_report = {"criteria": [dict(v, suggested_fix="") for v in prev_results.values()], "summary": "s"} if previous else None
        loop_decision = controller.decide(brief, report, {"passed": file_ok, "failures": [] if file_ok else ["bad size"]},
                                          repairs_used, max_repairs, prev_report)
        return audit_decision, loop_decision

    def test_same_action_for_every_outcome(self):
        cases = {
            "accepted_by_checks": dict(c1="pass", k1="pass"),
            "hold_for_inspection": dict(c1="uncertain", k1="pass"),
            "reject_technical": dict(c1="uncertain", k1="pass", file_ok=False),
            "stop_budget": dict(c1="fail", k1="pass", repairs_used=3),
            "stop_repeated_failure": dict(c1="fail", k1="pass", repairs_used=1, previous=("fail", "pass")),
        }
        for expected, kwargs in cases.items():
            audit_decision, loop_decision = self.both(**kwargs)
            self.assertEqual(audit_decision["action"], expected, kwargs)
            self.assertEqual(loop_decision["action"], expected, kwargs)

    def test_protected_failure_is_a_repair_from_the_clean_source_in_both(self):
        audit_decision, loop_decision = self.both(c1="pass", k1="fail")
        for decision in (audit_decision, loop_decision):
            self.assertEqual(decision["action"], "repair")
            self.assertEqual(decision["protected_failed"], ["K1"])
            self.assertIn("never this candidate", decision["start_from"])


@needs_pillow
class HistoryAndInputTests(Case):
    def setUp(self):
        super().setUp()
        self.contract()
        Image.new("RGB", (100, 100), "white").save(self.dir / "s.png")
        candidate = Image.new("RGB", (100, 100), "white")
        ImageDraw.Draw(candidate).rectangle((10, 10, 20, 20), fill="blue")
        candidate.save(self.dir / "c.png")
        self.mask = self.left_mask()

    def test_repair_count_comes_from_history(self):
        _, first, out = self.audit(self.dir / "s.png", self.dir / "c.png", self.review(c1="fail"), self.mask)
        self.assertEqual(first["action"], "repair")
        _, second, out2 = self.audit(self.dir / "s.png", self.dir / "c.png", self.review(c1="fail", k1="fail"),
                                     self.mask, previous=out)
        self.assertEqual(json.loads((out2 / "evidence.json").read_text())["repairs_used"], 1)
        result, _, _ = self.audit(self.dir / "s.png", self.dir / "c.png", self.review(c1="fail"), self.mask,
                                  previous=out, repairs_used=99)
        self.assertIn("does not match the round history", result.stderr)

    def test_accepted_round_cannot_start_another_repair(self):
        _, first, out = self.audit(self.dir / "s.png", self.dir / "c.png", self.review(), self.mask)
        self.assertEqual(first["action"], "accepted_by_checks")
        result, _, _ = self.audit(self.dir / "s.png", self.dir / "c.png", self.review(c1="fail"), self.mask, previous=out)
        self.assertIn("only a repair decision starts another round", result.stderr)

    def test_bad_types_give_clean_errors(self):
        for field, value in (("mode", []), ("version", True), ("version", 1.0)):
            data = json.loads((self.dir / "contract.json").read_text())
            data[field] = value
            (self.dir / "bad.json").write_text(json.dumps(data))
            result = run(AUDIT, "--contract", self.dir / "bad.json", "--source", self.dir / "s.png",
                         "--candidate", self.dir / "c.png", "--mask", self.mask, "--review", self.review(),
                         "--out", self.dir / f"bad-{field}-{value}")
            self.assertEqual(result.returncode, 2, (field, value, result.stderr))
            self.assertNotIn("Traceback", result.stderr)
        data = json.loads((self.dir / "contract.json").read_text())
        data["checks"][0]["target_id"] = []
        (self.dir / "bad.json").write_text(json.dumps(data))
        result = run(CONVERT, self.dir / "bad.json", "--out", self.dir / "brief.json")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_create_mode_rejects_keep_checks_in_both_scripts(self):
        self.contract(mode="create", locked=False)
        result = run(CONVERT, self.dir / "contract.json", "--out", self.dir / "brief.json")
        self.assertIn("create mode has none", result.stderr)

    @needs_jsonschema
    def test_review_py_accepts_results_format_and_derives_history(self):
        brief = self.dir / "brief.json"
        self.assertEqual(run(CONVERT, self.dir / "contract.json", "--out", brief).returncode, 0)
        common = [REVIEW, "--brief", brief, "--source", self.dir / "s.png", "--candidate", self.dir / "c.png"]
        first = run(*common, "--out", self.dir / "loop-0", "--report", self.review(c1="fail"))
        self.assertEqual(json.loads(first.stdout)["action"], "repair", first.stderr)
        second = run(*common, "--out", self.dir / "loop-1", "--report", self.review(c1="fail"),
                     "--previous", self.dir / "loop-0")
        self.assertEqual(json.loads(second.stdout)["action"], "stop_repeated_failure", second.stderr)
        self.assertEqual(json.loads((self.dir / "loop-1/run.json").read_text())["repairs_used"], 1)
        wrong = run(*common, "--out", self.dir / "loop-x", "--report", self.review(c1="fail"),
                    "--previous", self.dir / "loop-0", "--repairs-used", "3")
        self.assertIn("does not match the round history", wrong.stderr)

    @needs_jsonschema
    def test_review_py_invalid_review_always_exits_2(self):
        brief = self.dir / "brief.json"
        run(CONVERT, self.dir / "contract.json", "--out", brief)
        partial = self.dir / "partial.json"
        partial.write_text(json.dumps({"results": [{"id": "C1", "status": "pass", "evidence": "seen"}]}))
        common = [REVIEW, "--brief", brief, "--source", self.dir / "s.png", "--candidate", self.dir / "c.png"]
        for name, report in (("missing-id", partial), ("not-json", self.dir / "s.png")):
            result = run(*common, "--out", self.dir / name, "--report", report)
            self.assertEqual(result.returncode, 2, (name, result.stdout, result.stderr))
            self.assertEqual(json.loads((self.dir / name / "decision.json").read_text())["action"], "stop_invalid_review")

    @needs_jsonschema
    def test_invalid_review_is_reported_before_file_checks(self):
        brief = self.dir / "brief.json"
        run(CONVERT, self.dir / "contract.json", "--out", brief)
        Image.new("RGB", (100, 100), "white").save(self.dir / "c.jpg", "JPEG")
        partial = self.dir / "partial.json"
        partial.write_text(json.dumps({"results": [{"id": "C1", "status": "pass", "evidence": "seen"}]}))
        result = run(REVIEW, "--brief", brief, "--source", self.dir / "s.png", "--candidate", self.dir / "c.jpg",
                     "--out", self.dir / "order", "--report", partial)
        self.assertEqual((result.returncode, json.loads(result.stdout)["action"]), (2, "stop_invalid_review"))

    @needs_jsonschema
    def test_one_review_file_works_for_both_scripts(self):
        brief = self.dir / "brief.json"
        run(CONVERT, self.dir / "contract.json", "--out", brief)
        shared = self.dir / "shared.json"
        shared.write_text(json.dumps({"reviewer": "person at 100%", "criteria": [
            {"id": "C1", "status": "pass", "evidence": "seen", "suggested_fix": ""},
            {"id": "K1", "status": "pass", "evidence": "seen", "suggested_fix": ""}], "summary": "ok"}))
        loop = run(REVIEW, "--brief", brief, "--source", self.dir / "s.png", "--candidate", self.dir / "c.png",
                   "--out", self.dir / "shared-loop", "--report", shared)
        self.assertEqual(json.loads(loop.stdout)["action"], "accepted_by_checks", loop.stderr)
        _, decision, _ = self.audit(self.dir / "s.png", self.dir / "c.png", shared, self.mask)
        self.assertEqual(decision["action"], "accepted_by_checks")

    @needs_jsonschema
    def test_review_py_missing_candidate_is_a_clean_error(self):
        brief = self.dir / "brief.json"
        run(CONVERT, self.dir / "contract.json", "--out", brief)
        result = run(REVIEW, "--brief", brief, "--source", self.dir / "s.png", "--candidate", self.dir / "missing.png",
                     "--out", self.dir / "o", "--report", self.review())
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.installer = load("installer", ROOT / "scripts/install.py")
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self.tmp.name) / "skills"

    def tearDown(self):
        self.tmp.cleanup()

    def test_skill_list_is_derived_from_the_folder(self):
        self.assertEqual(set(self.installer.NAMES), {p.parent.name for p in SKILLS.glob("*/SKILL.md")})

    def test_replace_handles_a_file_where_a_skill_folder_was(self):
        self.installer.install(SKILLS, self.dest)
        target = self.dest / "image-verify"
        import shutil
        shutil.rmtree(target)
        target.write_text("not a folder")
        self.installer.install(SKILLS, self.dest, replace=True)
        self.assertTrue((target / "SKILL.md").is_file())

    def test_failed_copy_leaves_destination_unchanged(self):
        self.installer.install(SKILLS, self.dest)
        marker = self.dest / "image-loop/keep.txt"
        marker.write_text("user work")
        real_copy, calls = self.installer.shutil.copytree, []

        def flaky(*args, **kwargs):
            calls.append(1)
            if len(calls) == 5:
                raise OSError("disk full")
            return real_copy(*args, **kwargs)

        self.installer.shutil.copytree = flaky
        try:
            with self.assertRaises(OSError):
                self.installer.install(SKILLS, self.dest, replace=True)
        finally:
            self.installer.shutil.copytree = real_copy
        self.assertEqual(marker.read_text(), "user work")
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), sorted(self.installer.NAMES))

    def test_interrupted_replace_restores_every_skill(self):
        self.installer.install(SKILLS, self.dest)
        marker = self.dest / "image-loop/keep.txt"
        marker.write_text("user work")
        real_rename, calls = Path.rename, []

        def interrupted(path, target):
            if Path(target).parent == self.dest:
                calls.append(1)
                if len(calls) == 3:  # third new folder placed, then Ctrl-C
                    raise KeyboardInterrupt
            return real_rename(path, target)

        Path.rename = interrupted
        try:
            with self.assertRaises(KeyboardInterrupt):
                self.installer.install(SKILLS, self.dest, replace=True)
        finally:
            Path.rename = real_rename
        self.assertEqual(marker.read_text(), "user work")
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), sorted(self.installer.NAMES))
        self.assertEqual([p.name for p in self.dest.parent.iterdir()], ["skills"])  # staging removed

    def test_refuses_destinations_inside_the_repository(self):
        for inside in (ROOT / "plugins/image-studio", ROOT / "new-folder", SKILLS):
            with self.assertRaises(ValueError):
                self.installer.install(SKILLS, inside, replace=True)


class InheritedScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @unittest.skipUnless(importlib.util.find_spec("jsonschema"), "jsonschema is not installed")
    def test_validate_spec_rejects_nan(self):
        spec = (SKILLS / "image-edit-map/examples/image-spec.example.json").read_text()
        data = json.loads(spec)
        data["sections"][0]["bbox"][0] = float("nan")
        path = self.dir / "nan.json"
        path.write_text(json.dumps(data))
        result = run(SKILLS / "image-edit-map/scripts/validate_spec.py", path)
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_reconstruct_move_cannot_restyle(self):
        recon = load("reconstruct", SKILLS / "image-reconstruction/scripts/reconstruct.py")
        spec = json.loads((SKILLS / "image-reconstruction/examples/synthetic-scene.json").read_text())
        target = spec["elements"][0]["id"]
        spec["selections"] = [{"target_id": target, "action": "move", "properties": ["appearance.color"],
                               "instruction": "Move it", "destination_bbox": [0, 0, 0.1, 0.1],
                               "reference_ids": [], "preserve": [], "allow": []}]
        with self.assertRaises(Exception) as caught:
            recon.validate(spec)
        self.assertIn("move changes only bbox", str(caught.exception))

    def test_uncertain_comparison_retains_incumbent(self):
        advance = load("advance", SKILLS / "image-inspiration/scripts/advance.py")
        state = {"mode": "loop", "judge": "llm", "rounds_completed": 2, "max_rounds": 3, "images_used": 4,
                 "max_images": 9, "no_improvement_rounds": 0, "incumbent_id": "A",
                 "candidates": [{"id": "A", "checks": "pass"}, {"id": "B", "checks": "pass"}],
                 "judgment": {"by": "llm", "improved": None, "stop": False, "ranking": ["B", "A"],
                              "reason": "close call", "feedback": ""}}
        decision = advance.decide(state)
        self.assertEqual((decision["action"], decision["winner_id"], decision["ranked_first"]),
                         ("stop_uncertain_comparison", "A", "B"))
        # Overshooting a budget is a safe stop, as test_inspiration.test_budget_and_parent expects.
        self.assertEqual(advance.decide(dict(state, rounds_completed=5))['action'], 'stop_budget')


def write_rgb48_png(path, pixels, width, height):
    """Minimal 16-bit-per-channel RGB PNG writer (Pillow cannot write this mode)."""
    import struct
    import zlib

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\x00" + b"".join(struct.pack(">HHH", *pixels[y * width + x]) for x in range(width))
                    for y in range(height))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 16, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


@needs_pillow
class SecondAuditTests(Case):
    def setUp(self):
        super().setUp()
        self.contract()
        Image.new("RGB", (100, 100), "white").save(self.dir / "s.png")
        candidate = Image.new("RGB", (100, 100), "white")
        ImageDraw.Draw(candidate).rectangle((10, 10, 20, 20), fill="blue")
        candidate.save(self.dir / "c.png")
        self.mask = self.left_mask()

    def test_16bit_color_png_is_refused_not_silently_compared_at_8_bits(self):
        width = height = 100
        write_rgb48_png(self.dir / "s48.png", [(1000, 1000, 1000)] * (width * height), width, height)
        changed = [(1000, 1000, 1000)] * (width * height)
        changed[60 * width + 60] = (1001, 1000, 1000)  # below 8-bit resolution, inside the keep half
        write_rgb48_png(self.dir / "c48.png", changed, width, height)
        _, decision, _ = self.audit(self.dir / "s48.png", self.dir / "c48.png", self.review(), self.mask)
        self.assertEqual(decision["action"], "reject_technical")
        self.assertIn("16 bits per color channel", " ".join(decision["issues"]))

    def test_colored_and_float_masks_are_editable_where_nonzero(self):
        for name, mask in (("rgb", Image.new("RGB", (100, 100), (0, 0, 0))), ("f", Image.new("F", (100, 100), 0.0))):
            ImageDraw.Draw(mask).rectangle((0, 0, 49, 99), fill=(1, 0, 0) if name == "rgb" else 0.4)
            path = self.dir / f"mask-{name}.{'png' if name == 'rgb' else 'tif'}"
            mask.save(path)
            _, decision, _ = self.audit(self.dir / "s.png", self.dir / "c.png", self.review(), path)
            self.assertEqual(decision["action"], "accepted_by_checks", name)

    def test_forged_or_missing_history_is_refused(self):
        _, first, out = self.audit(self.dir / "s.png", self.dir / "c.png", self.review(c1="fail"), self.mask)
        evidence = json.loads((out / "evidence.json").read_text())
        evidence["repairs_used"] = -50
        (out / "evidence.json").write_text(json.dumps(evidence))
        forged, _, _ = self.audit(self.dir / "s.png", self.dir / "c.png", self.review(c1="fail"), self.mask, previous=out)
        self.assertIn("no valid repairs_used", forged.stderr)
        missing, _, _ = self.audit(self.dir / "s.png", self.dir / "c.png", self.review(), self.mask,
                                   previous=out / "does-not-exist")
        self.assertIn("does not exist", missing.stderr)

    def test_duplicate_json_keys_are_refused(self):
        review = self.dir / "dup.json"
        review.write_text('{"results": [{"id": "C1", "status": "fail", "status": "pass", "evidence": "e"},'
                          ' {"id": "K1", "status": "pass", "evidence": "e"}]}')
        result, _, _ = self.audit(self.dir / "s.png", self.dir / "c.png", review, self.mask)
        self.assertIn("duplicate JSON keys", result.stderr)

    @needs_jsonschema
    def test_contract_repair_limit_reaches_review_py(self):
        self.contract(max_repairs=0)
        brief = self.dir / "brief.json"
        run(CONVERT, self.dir / "contract.json", "--out", brief)
        result = run(REVIEW, "--brief", brief, "--source", self.dir / "s.png", "--candidate", self.dir / "c.png",
                     "--out", self.dir / "limit", "--report", self.review(c1="fail"))
        _, audit_decision, _ = self.audit(self.dir / "s.png", self.dir / "c.png", self.review(c1="fail"), self.mask)
        self.assertEqual(json.loads(result.stdout)["action"], "stop_budget")
        self.assertEqual(audit_decision["action"], "stop_budget")

    @needs_jsonschema
    def test_review_py_rounds_must_keep_brief_and_source(self):
        brief = self.dir / "brief.json"
        run(CONVERT, self.dir / "contract.json", "--out", brief)
        common = ["--source", self.dir / "s.png", "--candidate", self.dir / "c.png"]
        run(REVIEW, "--brief", brief, *common, "--out", self.dir / "r0", "--report", self.review(c1="fail"))
        data = json.loads(brief.read_text())
        data["intent"] = "Something else"
        (self.dir / "brief2.json").write_text(json.dumps(data))
        result = run(REVIEW, "--brief", self.dir / "brief2.json", *common, "--out", self.dir / "r1",
                     "--report", self.review(c1="fail"), "--previous", self.dir / "r0")
        self.assertIn("different brief", result.stderr)

    @needs_jsonschema
    def test_review_py_non_image_candidate_is_a_clean_error_without_output(self):
        brief = self.dir / "brief.json"
        run(CONVERT, self.dir / "contract.json", "--out", brief)
        (self.dir / "note.png").write_text("not an image")
        result = run(REVIEW, "--brief", brief, "--source", self.dir / "s.png", "--candidate", self.dir / "note.png",
                     "--out", self.dir / "bad", "--report", self.review())
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.dir / "bad").exists())


class SecondInstallerTests(unittest.TestCase):
    def setUp(self):
        self.installer = load("installer", ROOT / "scripts/install.py")
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self.tmp.name) / "skills"

    def tearDown(self):
        for path in self.dest.rglob("*"):
            if path.is_dir():
                path.chmod(0o755)
        self.tmp.cleanup()

    def test_locked_old_folder_still_gives_a_complete_new_install(self):
        self.installer.install(SKILLS, self.dest)
        (self.dest / "image-verify/scripts/marker.txt").write_text("old")
        locked = self.dest / "image-verify/references"
        locked.chmod(0o500)
        self.installer.install(SKILLS, self.dest, replace=True)
        self.assertEqual(sorted(p.name for p in self.dest.iterdir() if not p.name.startswith(".")), sorted(self.installer.NAMES))
        self.assertFalse((self.dest / "image-verify/scripts/marker.txt").exists())
        self.assertTrue((self.dest / "image-verify/references/decisions.md").is_file())

    def test_other_spelling_of_the_repository_is_refused(self):
        other = Path(str(ROOT).swapcase())
        if not other.exists() or not os.path.samefile(other, ROOT):
            self.skipTest("case-sensitive filesystem")
        with self.assertRaises(ValueError):
            self.installer.install(SKILLS, other / "tmp-install", replace=True)


class SecondInheritedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dense_criterion_dependencies_validate_quickly(self):
        import time
        recon = load("reconstruct", SKILLS / "image-reconstruction/scripts/reconstruct.py")
        spec = json.loads((SKILLS / "image-reconstruction/examples/synthetic-scene.json").read_text())
        target = spec["elements"][0]["id"]
        spec["criteria"]["hard"] = [{**spec["criteria"]["hard"][0], "id": f"H{i:02d}", "target_ids": [target],
                                     "depends_on": [f"H{j:02d}" for j in range(i)]} for i in range(60)]
        start = time.monotonic()
        try:
            recon.validate(spec)
        except Exception:
            pass  # other rules may reject the synthetic set; only the running time matters here
        self.assertLess(time.monotonic() - start, 5)

    def test_reconstruct_non_utf8_input_is_a_clean_error(self):
        path = self.dir / "latin1.json"
        path.write_bytes(b'{"name": "caf\xe9"}')
        result = run(SKILLS / "image-reconstruction/scripts/reconstruct.py", "validate", path)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_first_round_without_incumbent_is_not_a_stall(self):
        advance = load("advance", SKILLS / "image-inspiration/scripts/advance.py")
        state = {"mode": "loop", "judge": "llm", "rounds_completed": 1, "max_rounds": 3, "images_used": 2,
                 "max_images": 9, "no_improvement_rounds": 0, "incumbent_id": None,
                 "candidates": [{"id": "A", "checks": "pass"}, {"id": "B", "checks": "pass"}],
                 "judgment": {"by": "llm", "improved": False, "stop": False, "ranking": ["A", "B"],
                              "reason": "A is closer", "feedback": ""}}
        self.assertEqual(advance.decide(state)["no_improvement_rounds"], 0)

    @needs_jsonschema
    def test_validate_spec_image_checks(self):
        script = SKILLS / "image-edit-map/scripts/validate_spec.py"
        example = SKILLS / "image-edit-map/examples/image-spec.example.json"
        result = run(script, example, "--image-id", "A")
        self.assertIn("--image-id needs --image", result.stderr)
        self.assertEqual(result.returncode, 2)
