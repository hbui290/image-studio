"""compose_layers.py: text, numbers, and logos are placed on the art, not generated into it."""

import http.server
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from deps import needs_pillow

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/image-studio/skills/image-create/scripts/compose_layers.py"
FONTS = ["/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "C:/Windows/Fonts/arial.ttf"]
FONT = next((f for f in FONTS if Path(f).is_file()), None)
_CHROMIUM = []


def have_chromium():
    """Detect once whether Playwright and its Chromium can start; html rendering tests skip otherwise."""
    if not _CHROMIUM:
        ok = False
        if importlib.util.find_spec("playwright"):
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p: p.chromium.launch().close()
                ok = True
            except Exception:
                ok = False
        _CHROMIUM.append(ok)
    return _CHROMIUM[0]


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


@needs_pillow
class HtmlLayerChecksTests(unittest.TestCase):
    """html layer checks that run before Chromium starts, so they need no Playwright."""

    setUp = ComposeLayersTests.setUp
    tearDown = ComposeLayersTests.tearDown
    run_layout = ComposeLayersTests.run_layout

    def html(self, **extra):
        layer = {"html": "<div>5000+</div>", "box": [0.25, 0.25, 0.75, 0.75]}
        layer.update(extra)
        return self.run_layout({"background": "art.png", "layers": [layer]})

    def test_script_is_refused(self):
        run = self.html(html="<div>hi</div><SCRIPT>alert(1)</script>")
        self.assertEqual(run.returncode, 2, run.stdout)
        self.assertIn("<script> is not allowed", run.stderr)
        self.assertNotIn("Traceback", run.stderr)

    def test_font_path_escaping_the_folder_is_refused(self):
        sub = self.dir / "job"
        sub.mkdir()
        (self.dir / "outside.ttf").write_bytes(b"x")
        shutil.copy(self.dir / "art.png", sub / "art.png")
        (sub / "layout.json").write_text(json.dumps({"background": "art.png", "layers": [
            {"html": "<div>x</div>", "box": [0, 0, 1, 1], "fonts": {"Out": "../outside.ttf"}}]}))
        run = subprocess.run([sys.executable, str(SCRIPT), str(sub / "layout.json"), "--out", str(sub / "out.png")],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 2, run.stdout)
        self.assertIn("outside the layout folder", run.stderr)
        self.assertNotIn("Traceback", run.stderr)

    def test_missing_box_and_bad_overflow_exit_2(self):
        for layer in ({"html": "<b>x</b>"}, {"html": "<b>x</b>", "box": [0, 0, 1, 1], "overflow": "shrink"},
                      {"html": "", "box": [0, 0, 1, 1]}):
            run = self.run_layout({"background": "art.png", "layers": [layer]})
            self.assertEqual(run.returncode, 2, (layer, run.stdout))
            self.assertIn("html layer 1", run.stderr)
            self.assertNotIn("Traceback", run.stderr)

    def test_missing_playwright_exits_2_with_install_line_and_other_layers_still_work(self):
        fake = self.dir / "fake"
        (fake / "playwright").mkdir(parents=True)
        (fake / "playwright" / "__init__.py").write_text("raise ImportError('simulated: playwright is not installed')\n")
        env = dict(os.environ, PYTHONPATH=str(fake))
        argv = [sys.executable, str(SCRIPT), str(self.dir / "layout.json"), "--out", str(self.dir / "out.png")]
        (self.dir / "layout.json").write_text(json.dumps({"background": "art.png", "layers": [
            {"html": "<div>5000+</div>", "box": [0.25, 0.25, 0.75, 0.75]}]}))
        run = subprocess.run(argv, capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 2, run.stdout)
        self.assertIn("html layers need Playwright", run.stderr)
        self.assertIn("python3 -m playwright install chromium", run.stderr)
        self.assertNotIn("Traceback", run.stderr)
        (self.dir / "layout.json").write_text(json.dumps({"background": "art.png", "layers": [
            {"image": "logo.png", "x": 0.5, "y": 0.5, "width": 0.5}]}))
        run = subprocess.run(argv, capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 0, run.stderr)

    @unittest.skipUnless(importlib.util.find_spec("playwright"), "playwright is not installed")
    def test_missing_chromium_exits_2_with_install_line(self):
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(self.dir / "no-browsers"))
        (self.dir / "layout.json").write_text(json.dumps({"background": "art.png", "layers": [
            {"html": "<div>5000+</div>", "box": [0.25, 0.25, 0.75, 0.75]}]}))
        run = subprocess.run([sys.executable, str(SCRIPT), str(self.dir / "layout.json"), "--out", str(self.dir / "out.png")],
                             capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 2, run.stdout)
        self.assertIn("python3 -m playwright install chromium", run.stderr)
        self.assertNotIn("Traceback", run.stderr)


@needs_pillow
class HtmlLayerRenderTests(unittest.TestCase):
    """html layers rendered by Playwright Chromium; skipped when Playwright or its Chromium is missing."""

    setUp = ComposeLayersTests.setUp
    tearDown = ComposeLayersTests.tearDown
    run_layout = ComposeLayersTests.run_layout
    read_layout = ComposeLayersTests.read_layout
    outside_box_pixels = ComposeLayersTests.outside_box_pixels
    html = HtmlLayerChecksTests.html

    @classmethod
    def setUpClass(cls):
        if not have_chromium():
            raise unittest.SkipTest("Playwright Chromium is not available (python3 -m playwright install chromium)")

    def ink(self, box=(100, 50, 300, 150)):
        """Return (number of pixels that differ from the art inside box, ink width in px)."""
        from PIL import Image
        with Image.open(self.dir / "out.png") as out:
            out = out.convert("RGB")
            cols = [x for x in range(box[0], box[2]) for y in range(box[1], box[3]) if out.getpixel((x, y)) != (20, 40, 80)]
        return len(cols), (max(cols) - min(cols) + 1) if cols else 0

    def test_text_is_drawn_inside_the_box_only(self):
        run = self.html(css="div{color:#fff;font-size:30px}")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("html layer 1: box 100,50,300,150", run.stdout)
        self.assertGreater(self.ink()[0], 50)
        self.assertEqual(self.outside_box_pixels((100, 50, 300, 150)), 0)
        layer = self.read_layout()["layout"]["layers"][0]
        self.assertEqual(layer["html"], "<div>5000+</div>")
        self.assertEqual(layer["resolved"]["box_px"], [100, 50, 300, 150])

    @unittest.skipUnless(FONT, "no system font")
    def test_listed_font_file_is_used(self):
        (self.dir / "fonts").mkdir()
        shutil.copy(FONT, self.dir / "fonts" / "Brand.ttf")
        css = "div{color:#fff;font:40px 'Brand', monospace;white-space:nowrap}"
        run = self.html(html="<div>iiii</div>", css=css)
        self.assertEqual(run.returncode, 0, run.stderr)
        fallback = self.ink()[1]
        run = self.html(html="<div>iiii</div>", css=css, fonts={"Brand": "fonts/Brand.ttf"})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotEqual(self.ink()[1], fallback)
        self.assertLess(self.ink()[1], fallback)  # proportional "i" is narrower than monospace

    def test_broken_font_file_exits_2(self):
        (self.dir / "bad.ttf").write_text("not a font")
        run = self.html(css="div{font-family:Bad}", fonts={"Bad": "bad.ttf"})
        self.assertEqual(run.returncode, 2, run.stdout)
        self.assertIn("could not be loaded", run.stderr)
        self.assertNotIn("Traceback", run.stderr)

    def test_network_and_local_files_are_blocked(self):
        from PIL import Image
        hits = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200); self.send_header("Content-Type", "image/png"); self.end_headers()
                self.wfile.write((self.server.red).read_bytes())

            def log_message(self, *args):
                pass

        Image.new("RGB", (60, 60), (255, 0, 0)).save(self.dir / "red.png")
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        server.red = self.dir / "red.png"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}"
            run = self.html(
                html=(f'<img src="{url}/x.png" width="60" height="60"><link rel="stylesheet" href="{url}/s.css">'
                      f'<iframe src="{url}/f"></iframe><img src="{(self.dir / "red.png").as_uri()}" width="60" height="60">'
                      f'<div style="width:60px;height:60px;background:url({url}/bg.png)"></div>'),
                css=f'@import url("{url}/a.css"); body{{background-image:url({url}/b.png)}} img,iframe{{border:0}}',
                overflow="clip")
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(hits, [])
        with Image.open(self.dir / "out.png") as out:
            reds = sum(1 for p in out.convert("RGB").getdata() if p == (255, 0, 0))
        self.assertEqual(reds, 0)

    def test_same_input_gives_identical_png_bytes(self):
        css = "div{color:#F5C542;font:700 36px serif;padding:8px;text-shadow:0 0 4px #000}"
        self.assertEqual(self.html(css=css).returncode, 0)
        first = (self.dir / "out.png").read_bytes()
        self.assertEqual(self.html(css=css).returncode, 0)
        self.assertEqual((self.dir / "out.png").read_bytes(), first)

    def test_overflow_exits_2_unless_clip(self):
        css = "div{color:#fff;font-size:80px;white-space:nowrap}"
        run = self.html(html="<div>5000+ followers</div>", css=css)
        self.assertEqual(run.returncode, 2, run.stdout)
        self.assertIn("html layer does not fit its box", run.stderr)
        self.assertNotIn("Traceback", run.stderr)
        run = self.html(html="<div>5000+ followers</div>", css=css, overflow="clip")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.outside_box_pixels((100, 50, 300, 150)), 0)

    def test_text_outside_its_element_box_is_caught(self):
        cases = {"text-indent": ("<div>Hello</div>", "div{color:#fff;font-size:30px;text-indent:-60px}"),
                 "negative letter-spacing": ("<div>Hello</div>", "div{color:#fff;font-size:40px;letter-spacing:-40px}"),
                 "::before": ("<div class=t></div>", ".t{color:#fff;font-size:30px;text-indent:-60px}.t::before{content:'Hello'}"),
                 "text-shadow": ("<div>Hello</div>", "div{color:#fff;font-size:30px;text-align:right;text-shadow:30px 0 0 #fff}")}
        for case, (html, css) in cases.items():
            run = self.html(html=html, css=css)
            self.assertEqual(run.returncode, 2, (case, run.stdout))
            self.assertIn("html layer does not fit its box", run.stderr, case)
            self.assertNotIn("Traceback", run.stderr)

    def test_overflow_error_reports_the_left_and_top_offset(self):
        run = self.html(html="<div>Hello</div>", css="div{color:#fff;font-size:20px;margin:-30px 0 0 -40px}")
        self.assertEqual(run.returncode, 2, run.stdout)
        self.assertIn("starting at left -40 px, top -30 px", run.stderr)

    def test_full_height_image_fits_without_a_baseline_gap(self):
        svg = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='100'/%3E"
        run = self.html(html=f'<img src="{svg}">')
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_script_and_handlers_never_run(self):
        run = self.html(html='<img src="data:image/png;base64,AAAA" onerror="document.body.style.background=\'red\'"><div style="color:#fff">x</div>')
        self.assertEqual(run.returncode, 0, run.stderr)
        from PIL import Image
        with Image.open(self.dir / "out.png") as out:
            self.assertNotEqual(out.convert("RGB").getpixel((290, 140)), (255, 0, 0))


if __name__ == "__main__":
    unittest.main()
