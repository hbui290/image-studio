"""End-to-end checks for audit_candidate.py. Run: python -m unittest discover -s tests"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

SCRIPT = Path(__file__).resolve().parents[1] / "plugins/image-studio/skills/image-verify/scripts/audit_candidate.py"
SIZE = (100, 100)
EDIT_BOX = [10, 10, 31, 31]  # A: target that should change
MASK_BOX = (5, 5, 45, 45)    # white = editable


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.rounds = 0

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, name):
        return self.dir / name

    def image(self, name, mode="RGB", color="white", boxes=()):
        img = Image.new(mode, SIZE, color)
        draw = ImageDraw.Draw(img)
        for box, fill in boxes:
            draw.rectangle(box, fill=fill)
        img.save(self.path(name))
        return self.path(name)

    def mask(self, name="mask.png", fill=255, feather=None):
        img = Image.new("L", SIZE, 0)
        ImageDraw.Draw(img).rectangle(MASK_BOX, fill=fill)
        if feather is not None:
            img.putpixel((MASK_BOX[2] + 1, MASK_BOX[3] + 1), feather)
        img.save(self.path(name))
        return self.path(name)

    def contract(self, keep_box=(60, 60, 20, 20), locked=True, max_repairs=3):
        data = {"version": 1, "mode": "repair", "intent": "Recolor square A",
                "canvas": {"width": SIZE[0], "height": SIZE[1], "format": "PNG"},
                "targets": [{"id": "A", "name": "square", "bbox": EDIT_BOX},
                            {"id": "B", "name": "hand", "bbox": list(keep_box)}],
                "checks": [{"id": "C1", "target_id": "A", "kind": "change", "requirement": "Square is blue"},
                           {"id": "K1", "target_id": "B", "kind": "keep", "requirement": "Hand unchanged"}],
                "pixel_lock_outside_mask": locked, "max_repairs": max_repairs}
        self.path("contract.json").write_text(json.dumps(data))
        return self.path("contract.json")

    def review(self, c1="pass", k1="pass", name="review.json", k1_extra=None):
        k1_result = {"id": "K1", "status": k1, "evidence": "Looked at native pixels"}
        k1_result.update(k1_extra or {})
        results = [{"id": "C1", "status": c1, "evidence": "Looked at native pixels"}, k1_result]
        self.path(name).write_text(json.dumps({"results": results}))
        return self.path(name)

    def run_audit(self, candidate, review, source="source.png", mask="mask.png", previous=None, repairs_used=0):
        self.rounds += 1
        out = self.path(f"round-{self.rounds}")
        cmd = [sys.executable, str(SCRIPT), "--contract", str(self.path("contract.json")),
               "--candidate", str(candidate), "--review", str(review), "--out", str(out)]
        if source:
            cmd += ["--source", str(self.path(source))]
        if mask:
            cmd += ["--mask", str(self.path(mask))]
        if previous:
            cmd += ["--previous", str(previous), "--repairs-used", str(repairs_used)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        decision = json.loads(result.stdout) if result.returncode == 0 else None
        return result, decision, out

    def standard(self):
        self.image("source.png")
        self.mask()
        self.contract()
        return self.image("candidate.png", boxes=[((15, 15, 35, 35), "blue")])

    # Core behavior that already worked; guards against regressions.

    def test_clean_local_edit_is_accepted(self):
        _, decision, _ = self.run_audit(self.standard(), self.review())
        self.assertEqual(decision["action"], "accepted_by_checks")

    def test_one_pixel_outside_mask_is_rejected(self):
        self.standard()
        leak = self.image("leak.png", boxes=[((15, 15, 35, 35), "blue"), ((90, 90, 90, 90), "black")])
        _, decision, _ = self.run_audit(leak, self.review())
        self.assertEqual(decision["action"], "reject_technical")

    def test_claimed_change_without_pixels_is_rejected(self):
        self.standard()
        _, decision, _ = self.run_audit(self.path("source.png"), self.review())
        self.assertIn("C1: reported change", decision["issues"][0])

    def test_review_missing_an_id_is_an_error(self):
        candidate = self.standard()
        self.path("partial.json").write_text(json.dumps(
            {"results": [{"id": "C1", "status": "pass", "evidence": "seen"}]}))
        result, _, _ = self.run_audit(candidate, self.path("partial.json"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing IDs", result.stderr)

    def test_failed_change_requests_repair_then_stops_on_repeat(self):
        candidate = self.standard()
        _, first, out = self.run_audit(candidate, self.review(c1="fail"))
        self.assertEqual(first["action"], "repair")
        _, second, _ = self.run_audit(candidate, self.review(c1="fail"), previous=out, repairs_used=1)
        self.assertEqual(second["action"], "stop_repeated_failure")

    def test_repair_limit_stops(self):
        candidate = self.standard()
        self.contract(max_repairs=1)
        _, _, out = self.run_audit(candidate, self.review(c1="fail"))
        _, decision, _ = self.run_audit(candidate, self.review(c1="fail"), previous=out, repairs_used=1)
        self.assertEqual(decision["action"], "stop_limit")

    def test_previous_round_with_other_contract_is_refused(self):
        candidate = self.standard()
        _, _, out = self.run_audit(candidate, self.review(c1="fail"))
        self.contract(max_repairs=1)
        result, _, _ = self.run_audit(candidate, self.review(c1="fail"), previous=out, repairs_used=1)
        self.assertIn("different contract", result.stderr)

    def test_existing_output_directory_is_refused(self):
        candidate = self.standard()
        _, _, out = self.run_audit(candidate, self.review())
        self.rounds -= 1  # reuse the same folder name
        result, _, _ = self.run_audit(candidate, self.review())
        self.assertIn("already exists", result.stderr)

    # Fix 1: a protected target inside the editable mask must not be silently accepted.

    def test_repainted_keep_target_inside_mask_is_held(self):
        self.image("source.png")
        self.mask()
        self.contract(keep_box=(30, 30, 10, 10))  # hand sits inside the editable area
        candidate = self.image("candidate.png", boxes=[((10, 10, 45, 45), "blue")])
        _, decision, out = self.run_audit(candidate, self.review())
        self.assertEqual(decision["action"], "hold_for_inspection")
        self.assertEqual(decision["check_ids"], ["K1"])
        evidence = json.loads((out / "evidence.json").read_text())
        self.assertEqual(evidence["pixels"]["changed_by_target"]["B"], 100)

    def test_acknowledged_keep_change_is_accepted(self):
        self.image("source.png")
        self.mask()
        self.contract(keep_box=(30, 30, 10, 10))
        candidate = self.image("candidate.png", boxes=[((10, 10, 45, 45), "blue")])
        review = self.review(k1_extra={"acknowledged_changed_pixels": 100})
        _, decision, _ = self.run_audit(candidate, review)
        self.assertEqual(decision["action"], "accepted_by_checks")

    def test_acknowledgement_below_actual_change_is_held(self):
        self.image("source.png")
        self.mask()
        self.contract(keep_box=(30, 30, 10, 10))
        candidate = self.image("candidate.png", boxes=[((10, 10, 45, 45), "blue")])
        review = self.review(k1_extra={"acknowledged_changed_pixels": 20})
        _, decision, _ = self.run_audit(candidate, review)
        self.assertEqual(decision["action"], "hold_for_inspection")

    def test_invalid_acknowledgement_is_an_error(self):
        candidate = self.standard()
        result, _, _ = self.run_audit(candidate, self.review(k1_extra={"acknowledged_changed_pixels": -1}))
        self.assertIn("acknowledged_changed_pixels", result.stderr)

    # Fix 2: fully transparent pixels whose hidden RGB changed are not visible changes.

    def test_hidden_rgb_under_full_transparency_is_ignored(self):
        self.image("source.png", mode="RGBA", color=(255, 0, 0, 0))
        self.mask()
        self.contract()
        candidate = self.image("candidate.png", mode="RGBA", color=(0, 255, 0, 0),
                               boxes=[((15, 15, 35, 35), (0, 0, 255, 255))])
        _, decision, _ = self.run_audit(candidate, self.review())
        self.assertEqual(decision["action"], "accepted_by_checks")

    def test_visible_alpha_change_outside_mask_is_rejected(self):
        self.image("source.png", mode="RGBA", color=(255, 0, 0, 0))
        self.mask()
        self.contract()
        candidate = self.image("candidate.png", mode="RGBA", color=(255, 0, 0, 0),
                               boxes=[((15, 15, 35, 35), (0, 0, 255, 255)), ((90, 90, 90, 90), (255, 0, 0, 1))])
        _, decision, _ = self.run_audit(candidate, self.review())
        self.assertEqual(decision["action"], "reject_technical")

    # Fix 3: a feathered final mask follows the documented "every nonzero pixel is editable" rule.

    def test_feathered_mask_treats_nonzero_as_editable(self):
        self.image("source.png")
        self.mask(feather=128)
        self.contract()
        candidate = self.image("candidate.png", boxes=[((15, 15, 35, 35), "blue"),
                                                       ((MASK_BOX[2] + 1,) * 4, "blue")])
        _, decision, _ = self.run_audit(candidate, self.review())
        self.assertEqual(decision["action"], "accepted_by_checks")

    def test_feathered_mask_still_locks_black_pixels(self):
        self.image("source.png")
        self.mask(feather=128)
        self.contract()
        candidate = self.image("candidate.png", boxes=[((15, 15, 35, 35), "blue"), ((90, 90, 90, 90), "black")])
        _, decision, _ = self.run_audit(candidate, self.review())
        self.assertEqual(decision["action"], "reject_technical")


if __name__ == "__main__":
    unittest.main()
