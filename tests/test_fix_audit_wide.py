"""Regression tests for 16-bit/float audit fixes and compare_display input checks. Run: python -m unittest discover -s tests"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    raise unittest.SkipTest("Pillow is not installed")

SKILLS = Path(__file__).resolve().parents[1] / "plugins/image-studio/skills"
AUDIT = SKILLS / "image-verify/scripts/audit_candidate.py"
COMPARE = SKILLS / "image-enhance/scripts/compare_display.py"


def run(*cmd):
    return subprocess.run([sys.executable, *map(str, cmd)], capture_output=True, text=True)


class Wide(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def audit(self, source, candidate, kind="change", fmt="PNG", alpha=False, box=(0, 0, 50, 50)):
        """One check on one target; returns (decision, evidence)."""
        canvas = {"width": 100, "height": 100, "format": fmt}
        if alpha:
            canvas["alpha_required"] = True
        contract = {"version": 1, "mode": "repair" if source else "create", "intent": "Edit the corner",
                    "canvas": canvas, "targets": [{"id": "A", "name": "corner", "bbox": list(box)}],
                    "checks": [{"id": "C1", "target_id": "A", "kind": kind, "requirement": "As asked"}]}
        (self.dir / "contract.json").write_text(json.dumps(contract))
        (self.dir / "review.json").write_text(json.dumps({"results": [{"id": "C1", "status": "pass", "evidence": "seen"}]}))
        out = self.dir / f"out-{len(list(self.dir.glob('out-*')))}"
        cmd = [AUDIT, "--contract", self.dir / "contract.json", "--candidate", candidate,
               "--review", self.dir / "review.json", "--out", out]
        if source:
            cmd += ["--source", source]
        result = run(*cmd)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout), json.loads((out / "evidence.json").read_text())

    def gray16(self, name, value=1000, corner=None, **save):
        image = Image.new("I;16", (100, 100), value)
        if corner is not None:
            ImageDraw.Draw(image).rectangle((0, 0, 9, 9), fill=corner)
        image.save(self.dir / name, **save)
        return self.dir / name

    # Finding 1: tRNS on a 16-bit grayscale image is part of the pixel comparison.
    def test_16bit_transparency_dropped_counts_as_changed(self):
        source = self.gray16("s.png", corner=0, transparency=0)
        candidate = self.gray16("c.png", corner=0)
        decision, evidence = self.audit(source, candidate, kind="keep")
        self.assertEqual(evidence["pixels"]["changed_pixels"], 100)
        self.assertEqual(decision["action"], "hold_for_inspection")

    def test_16bit_pixels_transparent_in_both_are_unchanged(self):
        source = self.gray16("s.png", corner=0, transparency=0)
        candidate = self.gray16("c.png", corner=5, transparency=5)
        decision, evidence = self.audit(source, candidate, kind="keep")
        self.assertEqual(evidence["pixels"]["changed_pixels"], 0)
        self.assertEqual(decision["action"], "accepted_by_checks")

    # Finding 2: a visible change on a 16-bit image is 8 levels of 8 bits, i.e. 8 * 257 on the 16-bit scale.
    def test_16bit_change_below_eight_levels_is_barely_visible(self):
        source = self.gray16("s.png")
        candidate = Image.new("I;16", (100, 100), 1000)
        ImageDraw.Draw(candidate).rectangle((0, 0, 49, 49), fill=1000 + 8 * 257 - 1)
        candidate.save(self.dir / "c.png")
        decision, _ = self.audit(source, self.dir / "c.png")
        self.assertEqual(decision["action"], "hold_for_inspection")
        self.assertEqual(decision["barely_visible_change_pixels"], {"C1": 0})

    def test_16bit_change_of_eight_levels_is_visible(self):
        source = self.gray16("s.png")
        candidate = Image.new("I;16", (100, 100), 1000)
        ImageDraw.Draw(candidate).rectangle((0, 0, 49, 49), fill=1000 + 8 * 257)
        candidate.save(self.dir / "c.png")
        decision, _ = self.audit(source, self.dir / "c.png")
        self.assertEqual(decision["action"], "accepted_by_checks")

    def float_pair(self, delta):
        source = Image.new("F", (100, 100), 0.0)
        ImageDraw.Draw(source).rectangle((50, 0, 99, 99), fill=1.0)  # value range 0 to 1
        source.save(self.dir / "s.tif")
        candidate = source.copy()
        ImageDraw.Draw(candidate).rectangle((0, 0, 49, 49), fill=delta)
        candidate.save(self.dir / "c.tif")
        return self.audit(self.dir / "s.tif", self.dir / "c.tif", fmt="TIFF")[0]

    def test_float_change_is_scaled_by_the_value_range(self):
        self.assertEqual(self.float_pair(0.01)["action"], "hold_for_inspection")  # 0.01 of a 0-1 range: invisible
        self.assertEqual(self.float_pair(0.1)["action"], "accepted_by_checks")

    # Finding 3: alpha_required on 16-bit grayscale needs a pixel equal to the tRNS value.
    def test_16bit_trns_with_no_matching_pixel_is_opaque(self):
        candidate = self.gray16("c.png", transparency=65535)
        decision, _ = self.audit(None, candidate, alpha=True)
        self.assertEqual(decision["action"], "reject_technical")
        self.assertIn("no transparent pixels", " ".join(decision["issues"]))

    def test_16bit_trns_with_a_matching_pixel_is_transparent(self):
        candidate = self.gray16("c.png", corner=65535, transparency=65535)
        decision, _ = self.audit(None, candidate, alpha=True)
        self.assertEqual(decision["action"], "accepted_by_checks")

    # Finding 5: "below 0.5% of the box" is exact, not floor-divided.
    def test_twelve_visible_pixels_in_a_2500_pixel_box_are_held(self):
        Image.new("RGB", (100, 100), "white").save(self.dir / "s.png")
        candidate = Image.new("RGB", (100, 100), "white")
        ImageDraw.Draw(candidate).rectangle((0, 0, 3, 2), fill="black")  # 4 x 3 = 12 pixels = 0.48%
        candidate.save(self.dir / "c.png")
        decision, _ = self.audit(self.dir / "s.png", self.dir / "c.png")
        self.assertEqual(decision["action"], "hold_for_inspection")
        self.assertEqual(decision["barely_visible_change_pixels"], {"C1": 12})


class CompareInputs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def compare(self, source, candidate, width=800):
        source.save(self.dir / f"source.{'tif' if source.mode == 'F' else 'png'}")
        candidate.save(self.dir / "candidate.png")
        name = "source.tif" if source.mode == "F" else "source.png"
        return run(COMPARE, "--source", self.dir / name, "--candidate", self.dir / "candidate.png",
                   "--out", self.dir / "out", "--width", width)

    @staticmethod
    def striped(size):
        image = Image.new("RGB", size, (40, 60, 90))
        draw = ImageDraw.Draw(image)
        for i in range(0, max(size), 6):
            draw.line((i, 0, i + 20, size[1]), fill=(230, 200, 120))
            draw.line((0, i, size[0], i + 20), fill=(200, 230, 120))
        return image

    # Finding 4: aspect ratio is matched within rounding of one side, not an absolute 0.01.
    def test_faithful_resize_of_a_wide_banner_is_accepted(self):
        source = self.striped((1000, 30))
        result = self.compare(source, source.resize((1920, 58), Image.LANCZOS))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_crop_of_a_tall_strip_is_rejected(self):
        source = self.striped((30, 1000))
        result = self.compare(source, source.crop((0, 0, 30, 800)))
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("aspect ratios differ", result.stderr)

    # Finding 6: floating-point sources have no fixed scale, so they are refused.
    def test_float_source_is_refused(self):
        source = Image.new("F", (200, 100), 0.5)
        result = self.compare(source, Image.new("RGB", (200, 100), "gray"))
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("floating-point", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_display_too_large_for_a_tall_source_is_bad_input(self):
        strip = Image.new("RGB", (1, 20000), "gray")  # 16384 wide would be 16384 x 327680000 pixels
        result = self.compare(strip, strip, width=16384)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("too large", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
