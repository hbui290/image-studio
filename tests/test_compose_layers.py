"""compose_layers.py: text, numbers, and logos are placed on the art, not generated into it."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from deps import needs_pillow

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/image-studio/skills/image-create/scripts/compose_layers.py"
FONTS = ["/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "C:/Windows/Fonts/arial.ttf"]
FONT = next((f for f in FONTS if Path(f).is_file()), None)


@needs_pillow
class ComposeLayersTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        Image.new("RGB", (400, 200), (20, 40, 80)).save(self.dir / "art.png")
        logo = Image.new("RGBA", (100, 50), (0, 0, 0, 0))
        logo.paste((250, 200, 40, 255), (10, 10, 90, 40))
        logo.save(self.dir / "logo.png")

    def tearDown(self):
        self.tmp.cleanup()

    def run_layout(self, layout):
        (self.dir / "layout.json").write_text(json.dumps(layout))
        return subprocess.run([sys.executable, str(SCRIPT), str(self.dir / "layout.json"), "--out", str(self.dir / "out.png")],
                              capture_output=True, text=True)

    def test_logo_is_placed_by_center_and_width(self):
        run = self.run_layout({"background": "art.png", "layers": [{"image": "logo.png", "x": 0.5, "y": 0.5, "width": 0.5}]})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("box 100,50,300,150", run.stdout)  # 200x100 logo centered on a 400x200 canvas
        from PIL import Image
        with Image.open(self.dir / "out.png") as out:
            self.assertEqual(out.getpixel((200, 100))[:3], (250, 200, 40))  # opaque logo body
            self.assertEqual(out.getpixel((105, 55))[:3], (20, 40, 80))     # transparent logo margin shows the art

    @unittest.skipUnless(FONT, "no system font")
    def test_changing_text_is_one_run(self):
        layer = {"text": "5000+", "font": FONT, "size": 0.2, "color": "#FFFFFF", "x": 0.5, "y": 0.5}
        first = self.run_layout({"background": "art.png", "layers": [layer]})
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_layout({"background": "art.png", "layers": [dict(layer, text="5000+ followers")]})
        self.assertEqual(second.returncode, 0, second.stderr)
        width = lambda run: (lambda b: int(b[2]) - int(b[0]))(run.stdout.split("box ")[1].split(","))
        self.assertGreater(width(second), width(first))

    def test_bad_input_exits_2_without_traceback(self):
        cases = [{"background": "missing.png"},
                 {"background": "art.png", "layers": [{"image": "logo.png", "text": "x", "x": 0.5, "y": 0.5}]},
                 {"background": "art.png", "layers": [{"text": "x", "font": "/nope.ttf", "size": 0.1, "x": 0.5, "y": 0.5}]},
                 {"background": "art.png", "layers": [{"image": "logo.png", "x": 2, "y": 0.5}]}]
        for layout in cases:
            run = self.run_layout(layout)
            self.assertEqual(run.returncode, 2, (layout, run.stdout, run.stderr))
            self.assertNotIn("Traceback", run.stderr)

    def test_unknown_output_extension_exits_2(self):
        (self.dir / "layout.json").write_text(json.dumps({"background": "art.png", "layers": []}))
        run = subprocess.run([sys.executable, str(SCRIPT), str(self.dir / "layout.json"), "--out", str(self.dir / "o.xyz")],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertNotIn("Traceback", run.stderr)

    def test_layer_past_the_edge_is_clipped(self):
        run = self.run_layout({"background": "art.png", "layers": [{"image": "logo.png", "x": 0.0, "y": 0.0, "width": 0.5}]})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("box 0,0,100,50", run.stdout)

    def read_layout(self):
        from PIL import Image
        with Image.open(self.dir / "out.png") as out:
            return json.loads(out.text["image-studio-layout"])

    def outside_box_pixels(self, box):
        """Count pixels that differ from the art outside the pixel box (x0, y0, x1, y1)."""
        from PIL import Image
        with Image.open(self.dir / "out.png") as out:
            out = out.convert("RGB")
            return sum(1 for y in range(out.size[1]) for x in range(out.size[0])
                       if not (box[0] <= x < box[2] and box[1] <= y < box[3]) and out.getpixel((x, y)) != (20, 40, 80))

    def boxed(self, **extra):
        layer = {"text": "Grand opening this Saturday", "font": FONT, "size": 0.5, "box": [0.25, 0.25, 0.75, 0.75],
                 "color": "#FFFFFF", "stroke": 0.01, "stroke_color": "#FF0000"}
        layer.update(extra)
        return self.run_layout({"background": "art.png", "layers": [layer]})

    @unittest.skipUnless(FONT, "no system font")
    def test_shrink_fits_the_box_and_reduces_the_size(self):
        run = self.boxed(overflow="shrink", align="center")
        self.assertEqual(run.returncode, 0, run.stderr)
        info = self.read_layout()["layout"]["layers"][0]["resolved"]
        self.assertLess(info["size_px"], 100)  # asked for 0.5 * 200 px
        self.assertGreaterEqual(info["size_px"], 4)
        self.assertEqual(info["box_px"], [100, 50, 300, 150])
        self.assertEqual(self.outside_box_pixels((100, 50, 300, 150)), 0)

    @unittest.skipUnless(FONT, "no system font")
    def test_impossible_fit_exits_2_naming_the_layer(self):
        run = self.boxed(overflow="shrink", box=[0.5, 0.5, 0.52, 0.52])
        self.assertEqual(run.returncode, 2, run.stdout)
        self.assertIn("Grand opening", run.stderr)
        self.assertNotIn("Traceback", run.stderr)

    @unittest.skipUnless(FONT, "no system font")
    def test_wrap_stays_inside_the_box(self):
        run = self.boxed(size=0.12, overflow="wrap", align="right")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertGreater(len(self.read_layout()["layout"]["layers"][0]["resolved"]["lines"]), 1)
        self.assertEqual(self.outside_box_pixels((100, 50, 300, 150)), 0)

    @unittest.skipUnless(FONT, "no system font")
    def test_wrap_that_is_too_tall_exits_2_and_clip_cuts_it_off(self):
        self.assertEqual(self.boxed(overflow="wrap").returncode, 2)
        run = self.boxed(overflow="clip")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.outside_box_pixels((100, 50, 300, 150)), 0)

    @unittest.skipUnless(FONT, "no system font")
    def test_layout_is_embedded_in_the_png(self):
        run = self.run_layout({"background": "art.png", "layers": [
            {"text": "5000+", "font": FONT, "size": 0.2, "x": 0.5, "y": 0.5}]})
        self.assertEqual(run.returncode, 0, run.stderr)
        info = self.read_layout()
        self.assertEqual(info["canvas"], [400, 200])
        self.assertEqual(info["layout"]["layers"][0]["resolved"]["size_px"], 40)

    @unittest.skipUnless(FONT, "no system font")
    def test_bad_overflow_align_and_box_exit_2(self):
        for extra in ({"overflow": "spill"}, {"align": "middle"}, {"box": [0.8, 0.1, 0.2, 0.5]}, {"box": [0.1, 0.1]}):
            run = self.boxed(**extra)
            self.assertEqual(run.returncode, 2, (extra, run.stdout))
            self.assertNotIn("Traceback", run.stderr)
        run = self.run_layout({"background": "art.png", "layers": [
            {"text": "x", "font": FONT, "size": 0.2, "x": 0.5, "y": 0.5, "overflow": "wrap"}]})
        self.assertEqual(run.returncode, 2)


    @unittest.skipUnless(FONT, "no system font")
    def test_shrink_never_breaks_a_word(self):
        run = self.boxed(text="Supercalifragilisticexpialidocious word", overflow="shrink", box=[0.1, 0.1, 0.9, 0.9], size=0.3)
        self.assertEqual(run.returncode, 0, run.stderr)
        lines = self.read_layout()["layout"]["layers"][0]["resolved"]["lines"]
        self.assertIn("Supercalifragilisticexpialidocious", lines)

    @unittest.skipUnless(FONT, "no system font")
    def test_unicode_layout_is_readable_from_the_png(self):
        run = self.run_layout({"background": "art.png", "layers": [
            {"text": "Xin chào ✓", "font": FONT, "size": 0.2, "x": 0.5, "y": 0.5}]})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.read_layout()["layout"]["layers"][0]["text"], "Xin chào ✓")

    def test_broken_font_with_shrink_is_a_font_error(self):
        (self.dir / "bad.ttf").write_text("not a font")
        run = self.boxed(font=str(self.dir / "bad.ttf"), overflow="shrink")
        self.assertEqual(run.returncode, 2, run.stdout)
        self.assertIn("font", run.stderr)
        self.assertNotIn("does not fit", run.stderr)

    @unittest.skipUnless(FONT, "no system font")
    def test_blank_text_exits_2(self):
        for text in ("", "   ", "\n "):
            run = self.boxed(text=text)
            self.assertEqual(run.returncode, 2, (text, run.stdout))
            self.assertNotIn("Traceback", run.stderr)


if __name__ == "__main__":
    unittest.main()
