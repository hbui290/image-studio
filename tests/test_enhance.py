"""Checks for image-enhance/scripts/compare_display.py. Run: python -m unittest discover -s tests"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
except ImportError:  # pragma: no cover
    raise unittest.SkipTest("Pillow is not installed")

SCRIPT = Path(__file__).resolve().parents[1] / "plugins/image-studio/skills/image-enhance/scripts/compare_display.py"


class CompareDisplay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # "truth" has fine detail; the source is a soft, low-resolution copy of it.
        truth = Image.new("RGB", (1600, 900), (40, 60, 90))
        draw = ImageDraw.Draw(truth)
        for i in range(0, 1600, 12):
            draw.line((i, 0, i + 300, 900), fill=(230, 200, 120), width=2)
        for i in range(0, 900, 30):
            draw.ellipse((i, i // 2, i + 40, i // 2 + 40), outline=(250, 250, 250), width=2)
        self.truth = truth
        truth.resize((400, 225), Image.LANCZOS).save(self.dir / "source.png")
        self.source = Image.open(self.dir / "source.png").convert("RGB")

    def tearDown(self):
        self.tmp.cleanup()

    def compare(self, candidate, *extra, out="out"):
        candidate.save(self.dir / "candidate.png")
        run = subprocess.run([sys.executable, str(SCRIPT), "--source", str(self.dir / "source.png"), "--candidate",
                              str(self.dir / "candidate.png"), "--out", str(self.dir / out), "--width", "800", *extra],
                             capture_output=True, text=True)
        return run, (json.loads(run.stdout) if run.returncode == 0 else None)

    def test_real_detail_passes_and_writes_evidence(self):
        run, result = self.compare(self.truth, "--crop", "50,50,100,60")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(result["visible_improvement"], result)
        for name in ("before-after.png", "crop-1.png", "metrics.json"):
            self.assertTrue((self.dir / "out" / name).is_file(), name)

    def test_plain_resize_is_invisible(self):
        _, result = self.compare(self.source.resize(self.truth.size, Image.LANCZOS))
        self.assertFalse(result["visible_improvement"])
        self.assertIn("invisible", result["failures"][0])

    def test_sharpen_filter_alone_is_not_enough(self):
        plain = self.source.resize(self.truth.size, Image.LANCZOS)
        _, result = self.compare(plain.filter(ImageFilter.UnsharpMask(radius=1, percent=60, threshold=2)))
        self.assertFalse(result["visible_improvement"])

    def test_brightness_grade_is_reported_as_color_shift(self):
        _, result = self.compare(ImageEnhance.Brightness(self.truth).enhance(1.25))
        self.assertFalse(result["visible_improvement"])
        self.assertTrue(any("color" in f for f in result["failures"]), result["failures"])

    def test_different_framing_and_existing_output_are_clean_errors(self):
        run, _ = self.compare(self.truth.crop((0, 0, 900, 900)))
        self.assertEqual(run.returncode, 2)
        self.assertIn("aspect", run.stderr)
        (self.dir / "taken").mkdir()
        run, _ = self.compare(self.truth, out="taken")
        self.assertEqual(run.returncode, 2)

    def test_width_above_limit_is_refused(self):
        self.source.save(self.dir / "candidate.png")
        run = subprocess.run([sys.executable, str(SCRIPT), "--source", str(self.dir / "source.png"), "--candidate",
                              str(self.dir / "candidate.png"), "--out", str(self.dir / "w"), "--width", "200000"],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertIn("16384", run.stderr)

    def test_failed_crop_leaves_no_output_folder(self):
        run, _ = self.compare(self.source.resize((100, 56)), "--crop", "1,1,1,1")
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertFalse((self.dir / "out").exists())

    def test_16_bit_grayscale_source_matches_its_8_bit_copy(self):
        gray = self.source.convert("L")
        gray.convert("I").point(lambda v: v * 257).save(self.dir / "source.png")  # 16-bit grayscale PNG
        with Image.open(self.dir / "source.png") as saved:
            self.assertEqual(saved.mode, "I;16")
        _, deep = self.compare(self.truth.convert("L"), out="deep")
        gray.save(self.dir / "source.png")
        _, flat = self.compare(self.truth.convert("L"), out="flat")
        self.assertEqual(deep["failures"], flat["failures"])
        self.assertTrue(deep["visible_improvement"], deep)


if __name__ == "__main__":
    unittest.main()
