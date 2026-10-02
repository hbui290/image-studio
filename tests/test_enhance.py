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
        run, _ = self.compare(self.truth, "--crop", "399,0,5,5")
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertFalse((self.dir / "out").exists())

    def test_small_crop_on_a_smaller_candidate_still_works(self):
        run, _ = self.compare(self.source.resize((100, 56)), "--crop", "3,3,1,1")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue((self.dir / "out/crop-1.png").exists())

    def test_crop_at_the_far_edge_of_a_smaller_candidate_shows_real_pixels(self):
        run, _ = self.compare(self.source.resize((100, 56)), "--crop", "398,0,2,2")
        self.assertEqual(run.returncode, 0, run.stderr)
        with Image.open(self.dir / "out/crop-1.png") as crop:
            right = crop.convert("RGB").crop((crop.width // 2, 0, crop.width, crop.height))
            self.assertNotEqual(right.getextrema(), ((0, 0), (0, 0), (0, 0)), "candidate half is black padding")
            self.assertGreater(min(band[0] for band in right.getextrema()), 0, "black padding pixels")

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



class TransparentEdges(unittest.TestCase):
    """Cutouts: compare_display must see halos and speckles at the edge and a changed shape."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def cutout(self, name, radius=300, rim=0, seed=1):
        """A striped disc with a smooth (4x supersampled) edge, optionally inside a noisy gray rim."""
        import random
        size, big = 800, 3200
        art = Image.new("RGB", (size, size), (70, 110, 160))
        draw = ImageDraw.Draw(art)
        for x in range(0, size, 120):  # broad stripes: real interiors are calmer than a noisy rim
            draw.line((x, 0, x + 200, size), fill=(230, 210, 150), width=30)
        mask = Image.new("L", (big, big), 0)
        c, r = big // 2, 4 * (radius + rim)
        ImageDraw.Draw(mask).ellipse((c - r, c - r, c + r, c + r), fill=255)
        mask = mask.resize((size, size), Image.LANCZOS)
        if rim:  # an opaque rim of random grays: the halo/speckle left by a cutout from another backdrop
            rng = random.Random(seed)
            inner = Image.new("L", (size, size), 0)
            ImageDraw.Draw(inner).ellipse((400 - radius, 400 - radius, 400 + radius, 400 + radius), fill=255)
            noise = Image.new("RGB", (size, size))
            noise.putdata([(v, v, v) for v in (rng.randrange(60, 255) for _ in range(size * size))])
            art = Image.composite(art, noise, inner)
        art.putalpha(mask)
        path = self.dir / name
        art.save(path)
        return path

    def compare(self, source, candidate, out="out"):
        run = subprocess.run([sys.executable, str(SCRIPT), "--source", str(source), "--candidate", str(candidate),
                              "--out", str(self.dir / out), "--width", "400"], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def test_removing_a_speckled_rim_is_a_visible_improvement(self):
        result = self.compare(self.cutout("rim.png", rim=2), self.cutout("clean.png"))
        self.assertTrue(result["visible_improvement"], result)
        self.assertLessEqual(result["metrics"]["edge_ratio"], 0.8)
        self.assertTrue((self.dir / "out/before-after-light.png").is_file())

    def test_unchanged_cutout_is_not_an_improvement(self):
        rim = self.cutout("rim.png", rim=2)
        result = self.compare(rim, rim)
        self.assertFalse(result["visible_improvement"])
        self.assertEqual(result["metrics"]["edge_ratio"], 1.0)

    def test_adding_a_speckled_rim_fails(self):
        result = self.compare(self.cutout("clean.png"), self.cutout("rim.png", rim=2))
        self.assertTrue(any("noisier than the source" in f for f in result["failures"]), result)

    def test_shrinking_the_cutout_fails(self):
        result = self.compare(self.cutout("rim.png", rim=2), self.cutout("small.png", radius=270))
        self.assertTrue(any("cutout shape changed" in f for f in result["failures"]), result)
        self.assertLess(result["metrics"]["alpha_iou"], 0.97)

    def test_opaque_images_get_no_edge_check(self):
        Image.new("RGB", (400, 300), "gray").save(self.dir / "a.png")
        result = self.compare(self.dir / "a.png", self.dir / "a.png")
        self.assertNotIn("edge_ratio", result["metrics"])
        self.assertFalse((self.dir / "out/before-after-light.png").exists())


if __name__ == "__main__":
    unittest.main()
