"""Checks for image-enhance/scripts/export_social.py. Run: python -m unittest discover -s tests"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image, ImageDraw, PngImagePlugin
except ImportError:  # pragma: no cover
    raise unittest.SkipTest("Pillow is not installed")

SCRIPT = Path(__file__).resolve().parents[1] / "plugins/image-studio/skills/image-enhance/scripts/export_social.py"
SECRET = "a@b.c"


def png_chunks(path):
    data, pos, names = path.read_bytes(), 8, []
    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        names.append(data[pos + 4:pos + 8].decode("latin-1"))
        pos += 12 + length
    return names


class ExportSocial(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def source(self, size=(2000, 1000), name="src.png", **save):
        image = Image.new("RGB", size, (30, 40, 60))
        path = self.dir / name
        image.save(path, **save)
        return path

    def run_export(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)

    def assertClean(self, run, code):
        self.assertEqual(run.returncode, code, run.stdout + run.stderr)
        self.assertNotIn("Traceback", run.stderr)

    def test_presets_and_custom_size(self):
        src = self.source((1200, 1200))
        cases = {"x-landscape": (1600, 900), "x-square": (1080, 1080), "x-portrait": (1080, 1350),
                 "nft-portrait": (1024, 1536)}
        for preset, size in cases.items():
            for fit in ("cover", "pad"):
                out = self.dir / f"{preset}-{fit}.png"
                self.assertClean(self.run_export("--in", src, "--out", out, "--preset", preset, "--fit", fit), 0)
                with Image.open(out) as image:
                    self.assertEqual(image.size, size, (preset, fit))
        out = self.dir / "custom.jpg"
        self.assertClean(self.run_export("--in", src, "--out", out, "--size", "800x600"), 0)
        with Image.open(out) as image:
            self.assertEqual((image.size, image.format), ((800, 600), "JPEG"))

    def test_cover_keeps_focus(self):
        image = Image.new("RGB", (2000, 1000), (0, 0, 255))
        ImageDraw.Draw(image).rectangle((1700, 400, 1900, 600), fill=(255, 0, 0))
        src = self.dir / "focus.png"
        image.save(src)
        out, report = self.dir / "out.png", self.dir / "report.json"
        run = self.run_export("--in", src, "--out", out, "--preset", "x-square", "--focus", "1700,400,1900,600",
                              "--report", report)
        self.assertClean(run, 0)
        data = json.loads(report.read_text())
        x0, y0, x1, y1 = data["crop_box"]
        self.assertTrue(x0 <= 1700 and y0 <= 400 and x1 >= 1900 and y1 >= 600, data["crop_box"])
        fx0, fy0, fx1, fy1 = data["focus"]["output_box"]
        with Image.open(out) as result:
            self.assertEqual(result.convert("RGB").getpixel((round((fx0 + fx1) / 2), round((fy0 + fy1) / 2))), (255, 0, 0))
        # The centered default would have cut the red square out entirely.
        out2 = self.dir / "centered.png"
        self.assertClean(self.run_export("--in", src, "--out", out2, "--preset", "x-square"), 0)
        with Image.open(out2) as result:
            self.assertNotIn((255, 0, 0), {color for _, color in result.convert("RGB").getcolors(1 << 21)})

    def test_impossible_focus_exits_1_and_suggests_pad(self):
        src, out = self.source(), self.dir / "out.png"
        run = self.run_export("--in", src, "--out", out, "--preset", "x-square", "--focus", "100,100,1900,900")
        self.assertClean(run, 1)
        self.assertIn("--fit pad", run.stderr)
        self.assertFalse(out.exists())

    def test_safe_box_too_close_to_edge_exits_1(self):
        src, out, report = self.source((1600, 900)), self.dir / "out.png", self.dir / "r.json"
        run = self.run_export("--in", src, "--out", out, "--preset", "x-landscape", "--safe", "0,0,100,100",
                              "--safe", "700,400,900,500", "--report", report)
        self.assertClean(run, 1)
        self.assertIn("--safe box 1", run.stderr)
        self.assertIn("left edge", run.stderr)
        self.assertIn("top edge", run.stderr)
        self.assertNotIn("--safe box 2", run.stderr)
        self.assertFalse(out.exists())
        data = json.loads(report.read_text())
        self.assertFalse(data["ok"])
        self.assertEqual([b["ok"] for b in data["safe_boxes"]], [False, True])
        # Inside the margin: passes.
        run = self.run_export("--in", src, "--out", out, "--preset", "x-landscape", "--safe", "100,100,200,200")
        self.assertClean(run, 0)

    def test_png_text_metadata_removed_and_value_never_printed(self):
        info = PngImagePlugin.PngInfo()
        info.add_text("email", SECRET)
        info.add_itxt("Author", SECRET, zip=True)
        info.add_text("Comment", SECRET, zip=True)
        src = self.source(name="meta.png", pnginfo=info)
        out, report = self.dir / "clean.png", self.dir / "r.json"
        run = self.run_export("--in", src, "--out", out, "--preset", "x-square", "--report", report)
        self.assertClean(run, 0)
        self.assertNotIn(SECRET, run.stdout + run.stderr)
        self.assertNotIn(SECRET, report.read_text())
        self.assertIn("tEXt:<non-standard keyword>", run.stdout)
        self.assertIn("iTXt:Author", run.stdout)
        self.assertNotIn(SECRET.encode(), out.read_bytes())
        self.assertEqual(set(png_chunks(out)) - {"IHDR", "PLTE", "tRNS", "IDAT", "IEND"}, set())
        with Image.open(out) as image:
            self.assertEqual(getattr(image, "text", {}), {})
        self.assertEqual(json.loads(report.read_text())["remaining_metadata"], [])

    def test_jpeg_exif_removed_and_value_never_printed(self):
        exif = Image.Exif()
        exif[0x013B] = SECRET  # Artist
        exif[0x8298] = SECRET  # Copyright
        src = self.source((1200, 1200), name="meta.jpg", exif=exif.tobytes(), comment=SECRET.encode())
        out = self.dir / "clean.jpg"
        run = self.run_export("--in", src, "--out", out, "--preset", "x-portrait")
        self.assertClean(run, 0)
        self.assertNotIn(SECRET, run.stdout + run.stderr)
        self.assertIn("EXIF:Artist", run.stdout)
        self.assertNotIn(SECRET.encode(), out.read_bytes())
        with Image.open(out) as image:
            self.assertEqual(len(image.getexif()), 0)
            self.assertNotIn("exif", image.info)
            self.assertNotIn("comment", image.info)
            self.assertNotIn("icc_profile", image.info)

    def test_color_profile_converted_then_dropped(self):
        try:
            from PIL import ImageCms
        except ImportError:  # pragma: no cover
            self.skipTest("Pillow built without ImageCms")
        icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        src = self.source(name="icc.png", icc_profile=icc)
        out = self.dir / "out.png"
        run = self.run_export("--in", src, "--out", out, "--preset", "x-square")
        self.assertClean(run, 0)
        self.assertIn("iCCP", run.stdout)
        self.assertNotIn("iCCP", png_chunks(out))
        with Image.open(out) as image:
            self.assertNotIn("icc_profile", image.info)
            self.assertLessEqual(max(abs(a - b) for a, b in zip(image.getpixel((540, 540)), (30, 40, 60))), 2)

    def test_filename_slug_suggested_not_applied(self):
        src = self.source()
        out = self.dir / "ảnh post X.png"
        run = self.run_export("--in", src, "--out", out, "--preset", "x-square")
        self.assertClean(run, 0)
        self.assertIn("anh-post-x.png", run.stdout)
        self.assertTrue(out.exists())

    def test_bad_input_exits_2(self):
        src = self.source((200, 200))
        out = self.dir / "out.png"
        bad = self.dir / "bad.png"
        bad.write_bytes(b"not an image")
        cases = [
            ("--in", self.dir / "missing.png", "--out", out, "--preset", "x-square"),
            ("--in", bad, "--out", out, "--preset", "x-square"),
            ("--in", src, "--out", out, "--size", "0x10"),
            ("--in", src, "--out", out, "--preset", "x-square", "--focus", "1,2,3"),
            ("--in", src, "--out", out, "--preset", "x-square", "--focus", "0,0,300,100"),
            ("--in", src, "--out", out, "--preset", "x-square", "--margin", "0.6"),
            ("--in", src, "--out", out, "--preset", "x-square", "--pad-color", "red"),
            ("--in", src, "--out", self.dir / "out.gif", "--preset", "x-square"),
            ("--in", src, "--out", out, "--preset", "x-square", "--format", "jpeg"),
            ("--in", src, "--out", src, "--preset", "x-square"),
            ("--in", src, "--out", out, "--preset", "x-landscape"),  # 200 px -> 1600 px is an 8x upscale
        ]
        for args in cases:
            run = self.run_export(*args)
            self.assertClean(run, 2)
            self.assertTrue(run.stderr.strip(), args)
        self.assertFalse(out.exists())

    def test_missing_report_or_out_folder_exits_2(self):
        src = self.source((1600, 900))
        for args in (("--out", self.dir / "out.png", "--report", self.dir / "no" / "r.json"),
                     ("--out", self.dir / "no" / "out.png")):
            run = self.run_export("--in", src, "--preset", "x-landscape", *args)
            self.assertClean(run, 2)
            self.assertIn("folder", run.stderr)
        self.assertFalse((self.dir / "out.png").exists())

    def test_focus_with_pad_exits_2(self):
        src = self.source((1600, 900))
        run = self.run_export("--in", src, "--out", self.dir / "o.png", "--preset", "x-square", "--fit", "pad",
                              "--focus", "0,0,100,100")
        self.assertClean(run, 2)
        self.assertIn("--focus", run.stderr)

    def test_format_must_match_extension(self):
        src = self.source((1600, 900))
        run = self.run_export("--in", src, "--out", self.dir / "o.webp", "--preset", "x-landscape", "--format", "png")
        self.assertClean(run, 2)
        self.assertFalse((self.dir / "o.webp").exists())

    def test_non_standard_png_keyword_not_printed(self):
        info = PngImagePlugin.PngInfo()
        info.add_text("user-at-b.c", "x")
        info.add_text("Author", "x")
        src = self.source(name="kw.png", pnginfo=info)
        run = self.run_export("--in", src, "--out", self.dir / "o.png", "--preset", "x-square")
        self.assertClean(run, 0)
        self.assertNotIn("user-at-b.c", run.stdout + run.stderr)
        self.assertIn("tEXt:Author", run.stdout)
        self.assertIn("tEXt:<non-standard keyword>", run.stdout)

    def test_adobe_app14_labelled(self):
        src = self.source((1200, 1200), name="adobe.jpg")
        data = src.read_bytes()
        payload = b"Adobe" + bytes([1, 0, 0, 0, 0, 0, 1])  # DCTEncodeVersion 0x0100: no NUL right after "Adobe"
        segment = b"\xff\xee" + (len(payload) + 2).to_bytes(2, "big") + payload
        src.write_bytes(data[:2] + segment + data[2:])
        run = self.run_export("--in", src, "--out", self.dir / "o.png", "--preset", "x-square")
        self.assertClean(run, 0)
        self.assertIn("APP14:Adobe", run.stdout)
        self.assertNotIn("unknown", run.stdout)

    def test_exif_listed_when_exif_parsing_fails(self):
        sys.path.insert(0, str(SCRIPT.parent))
        try:
            import export_social
        finally:
            sys.path.pop(0)
        from unittest import mock

        exif = Image.Exif()
        exif[0x013B] = SECRET
        src = self.source((100, 100), name="e.webp", exif=exif.tobytes())
        with mock.patch("PIL.ExifTags.IFD", None, create=True), Image.open(src) as image:
            names = export_social.file_metadata(src, image)
        self.assertIn("EXIF:Artist", names)
        with mock.patch.object(Image.Image, "getexif", side_effect=AttributeError), Image.open(src) as image:
            names = export_social.file_metadata(src, image)
        self.assertIn("EXIF", names)

    def test_upscale_warns(self):
        src = self.source((800, 450))
        run = self.run_export("--in", src, "--out", self.dir / "out.png", "--preset", "x-landscape")
        self.assertClean(run, 0)
        self.assertIn("upscaling 2.00x", run.stdout)


if __name__ == "__main__":
    unittest.main()
