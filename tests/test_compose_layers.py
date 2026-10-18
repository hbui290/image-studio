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


if __name__ == "__main__":
    unittest.main()
