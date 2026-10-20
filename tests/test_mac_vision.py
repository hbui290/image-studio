"""mac_vision.py: Apple Vision cutout and OCR text check (macOS only; skipped elsewhere)."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from deps import needs_pillow

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/image-studio/skills/image-verify/scripts/mac_vision.py"
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
ON_MAC = sys.platform == "darwin" and shutil.which("swiftc") and Path(FONT).is_file()


@needs_pillow
@unittest.skipUnless(ON_MAC, "needs macOS with swiftc")
class MacVisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PIL import Image, ImageDraw, ImageFont
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.env = dict(os.environ, IMAGE_STUDIO_HOME=str(cls.dir / "home"))  # helper is built once for the class
        img = Image.new("RGB", (900, 300), (20, 30, 60))
        draw = ImageDraw.Draw(img)
        draw.text((60, 60), "5000+ FOLLOWERS", font=ImageFont.truetype(FONT, 90), fill=(250, 220, 90))
        img.save(cls.dir / "banner.png")
        subject = Image.new("RGB", (600, 600), (235, 235, 235))
        ImageDraw.Draw(subject).ellipse((150, 120, 450, 480), fill=(200, 40, 40))
        subject.save(cls.dir / "subject.png")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_tool(self, *args):
        run = subprocess.run([sys.executable, str(SCRIPT)] + [str(a) for a in args], capture_output=True, text=True,
                             env=self.env, timeout=600)
        self.assertNotIn("Traceback", run.stderr)
        return run

    def test_ocr_reads_and_checks_expected_text(self):
        ok = self.run_tool("ocr", self.dir / "banner.png", "--expect", "5000+", "--expect", "followers")
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn("All 2 expected texts found", ok.stdout)
        wrong = self.run_tool("ocr", self.dir / "banner.png", "--expect", "5,000+")
        self.assertEqual(wrong.returncode, 1, wrong.stdout + wrong.stderr)
        self.assertIn("MISSING", wrong.stderr)

    def test_cutout_writes_mask_or_reports_nothing(self):
        run = self.run_tool("cutout", self.dir / "subject.png", self.dir / "cut")
        self.assertIn(run.returncode, (0, 1), run.stderr)
        if run.returncode == 0:
            for name in ("cutout.png", "mask.png"):
                self.assertTrue((self.dir / "cut" / name).is_file(), name)

    def test_timeout_after_the_command_and_bad_values(self):
        ok = self.run_tool("ocr", self.dir / "banner.png", "--expect", "5000+", "--timeout", "120")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        for value in ("0", "-5"):
            bad = self.run_tool("ocr", self.dir / "banner.png", "--timeout", value)
            self.assertEqual(bad.returncode, 2, bad.stderr)
            self.assertIn("--timeout", bad.stderr)

    def test_hands_on_an_image_without_hands_reports_none(self):
        run = self.run_tool("hands", self.dir / "banner.png")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("No hands", run.stderr)

    def test_bad_input_exits_2(self):
        self.assertEqual(self.run_tool("ocr", self.dir / "missing.png").returncode, 2)
        (self.dir / "bad.png").write_text("not an image")
        self.assertEqual(self.run_tool("ocr", self.dir / "bad.png").returncode, 2)
        self.assertEqual(self.run_tool("cutout", self.dir / "subject.png", self.dir / "c2", "--point", "-5", "1").returncode, 2)


if __name__ == "__main__":
    unittest.main()
