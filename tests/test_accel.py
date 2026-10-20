"""Optional numpy/OpenCV engine (accel.py): engine choice, Pillow/fast parity, align-check --auto, mask-from-diff, seam_grad.

Parity tests run each accelerated command with --engine pillow and --engine fast on the same synthetic inputs and
require the same exit code and the same numbers within 1% (or one unit of the last printed digit). The fast side
skips itself when numpy or OpenCV is missing. A stub numpy package on PYTHONPATH simulates a machine without them.
"""

import contextlib
import importlib.util
import io
import json
import os
import random
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from deps import needs_fast  # noqa: E402
from test_studio_state import SCRIPT, StudioBase, load_module  # noqa: E402  (skips this module too when Pillow is missing)

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

FAST = bool(importlib.util.find_spec("numpy") and importlib.util.find_spec("cv2"))
FAST_ONLY = ("seam_grad:",)  # report-only lines the fast engine adds
NUM = re.compile(r"-?\d+(?:\.\d+)?")


def texture(size, seed):
    """Deterministic textured RGB image: random colored rectangles and ellipses, slightly blurred."""
    rnd = random.Random(seed)
    img = Image.new("RGB", size, (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
    d = ImageDraw.Draw(img)
    w, h = size
    for _ in range(w * h // 600):
        x, y = rnd.randrange(w), rnd.randrange(h)
        box = (x, y, x + rnd.randrange(4, 40), y + rnd.randrange(4, 40))
        fill = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
        (d.rectangle if rnd.random() < 0.5 else d.ellipse)(box, fill=fill)
    return img.filter(ImageFilter.GaussianBlur(1))


def numbers(text):
    """Comparable output: engine-specific lines dropped, every number with its printed decimals."""
    lines = [ln for ln in text.splitlines()
             if not ln.startswith("Engine:") and not ln.startswith(FAST_ONLY)]
    words = [NUM.sub("#", ln) for ln in lines]
    nums = [(float(m), len(m.split(".")[1]) if "." in m else 0) for ln in lines for m in NUM.findall(ln)]
    return words, nums


class EngineTests(StudioBase):
    """--engine / IMAGE_STUDIO_ENGINE choose the engine, print it, and refuse fast without numpy/OpenCV."""

    def setUp(self):
        super().setUp()
        texture((120, 90), 1).save(self.project / "a.png")
        b = Image.open(self.project / "a.png").copy(); ImageDraw.Draw(b).rectangle((40, 30, 70, 60), fill=(250, 0, 0))
        b.save(self.project / "b.png")
        m = Image.new("L", (120, 90), 0); m.paste(255, (40, 30, 71, 61)); m.save(self.project / "m.png")
        blocker = self.project / "blocked"
        (blocker / "numpy").mkdir(parents=True)
        (blocker / "numpy" / "__init__.py").write_text("raise ImportError('numpy blocked for this test')\n")
        self.no_libs = {"PYTHONPATH": str(blocker)}
        self.commands = {
            "blend": ["blend", "--base", "a.png", "--patch", "b.png", "--mask", "m.png", "--no-align-check", "--out", "o.png"],
            "edit-check": ["edit-check", "--before", "a.png", "--after", "b.png", "--mask", "m.png", "--out", "v.png"],
            "shape-check": ["shape-check", "--before-mask", "m.png", "--after-mask", "m.png"],
            "axis-check": ["axis-check", "--image", "a.png", "--points", "5,5", "60,45", "110,85"],
            "mask-from-diff": ["mask-from-diff", "--before", "a.png", "--after", "b.png", "--out", "d.png"],
        }

    def test_every_accelerated_command_prints_its_engine(self):
        for name, args in self.commands.items():
            run = self.run_cli(*args, "--engine", "pillow")
            self.assertIn(run.returncode, (0, 1), (name, run.stdout, run.stderr))
            self.assertEqual(run.stdout.splitlines()[0], "Engine: pillow", name)
            run = self.run_cli(*args, env_extra={"IMAGE_STUDIO_ENGINE": "pillow"})
            self.assertEqual(run.stdout.splitlines()[0], "Engine: pillow", name)

    def test_without_numpy_auto_is_pillow_and_fast_exits_2_with_install_hint(self):
        for name, args in self.commands.items():
            run = self.run_cli(*args, env_extra=self.no_libs)
            self.assertIn(run.returncode, (0, 1), (name, run.stdout, run.stderr))
            self.assertEqual(run.stdout.splitlines()[0], "Engine: pillow", name)
            for extra, env in ((["--engine", "fast"], {}), ([], {"IMAGE_STUDIO_ENGINE": "fast"})):
                run = self.run_cli(*args, *extra, env_extra=dict(self.no_libs, **env))
                self.assertEqual(run.returncode, 2, (name, extra, run.stdout, run.stderr))
                self.assertIn("pip install numpy==2.0.2 opencv-python-headless==4.11.0.86", run.stderr)
        run = self.run_cli("align-check", "--base", "a.png", "--patch", "b.png", "--auto", "--out-dir", "al", env_extra=self.no_libs)
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn("needs numpy and OpenCV", run.stderr); self.assertFalse((self.project / "al").exists())

    def test_unknown_engine_exits_2(self):
        run = self.run_cli(*self.commands["blend"], env_extra={"IMAGE_STUDIO_ENGINE": "gpu"})
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr); self.assertIn("IMAGE_STUDIO_ENGINE", run.stderr)
        run = self.run_cli(*self.commands["blend"], "--engine", "gpu")
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertFalse((self.project / "o.png").exists())

    def test_blank_environment_is_unset(self):
        for blank in (" ", "", "\t"):
            run = self.run_cli(*self.commands["shape-check"], env_extra={"IMAGE_STUDIO_ENGINE": blank})
            self.assertEqual(run.returncode, 0, (blank, run.stdout, run.stderr))
            self.assertEqual(run.stdout.splitlines()[0], "Engine: numpy/opencv" if FAST else "Engine: pillow")

    def test_engine_line_comes_before_an_error(self):
        env = dict(os.environ, IMAGE_STUDIO_HOME=str(self.home))
        run = subprocess.run([sys.executable, str(SCRIPT), "blend", "--base", "a.png", "--patch", "missing.png", "--mask", "m.png",
                              "--no-align-check", "--out", "o.png", "--engine", "pillow"], cwd=str(self.project), env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.assertEqual(run.returncode, 2, run.stdout)
        self.assertTrue(run.stdout.startswith("Engine: pillow\n"), run.stdout)

    @needs_fast
    def test_flag_wins_over_environment(self):
        run = self.ok(*self.commands["shape-check"], "--engine", "fast", env_extra={"IMAGE_STUDIO_ENGINE": "pillow"})
        self.assertEqual(run.stdout.splitlines()[0], "Engine: numpy/opencv")
        run = self.ok(*self.commands["shape-check"], "--engine", "pillow", env_extra={"IMAGE_STUDIO_ENGINE": "fast"})
        self.assertEqual(run.stdout.splitlines()[0], "Engine: pillow")


class ParityTests(StudioBase):
    """The same verdict, exit code and numbers (within 1%) from the Pillow and the numpy/OpenCV engine."""

    def both(self, *args):
        pillow = self.run_cli(*args, "--engine", "pillow")
        self.assertIn(pillow.returncode, (0, 1), pillow.stdout + pillow.stderr)
        self.assertEqual(pillow.stdout.splitlines()[0], "Engine: pillow")
        try:
            import numpy, cv2  # noqa: F401
        except ImportError:
            return pillow, None
        fast = self.run_cli(*args, "--engine", "fast")
        self.assertEqual(fast.stdout.splitlines()[0], "Engine: numpy/opencv")
        self.assertEqual(fast.returncode, pillow.returncode, pillow.stdout + "\n---\n" + fast.stdout)
        (pw, pn), (fw, fn) = numbers(pillow.stdout), numbers(fast.stdout)
        self.assertEqual(pw, fw, pillow.stdout + "\n---\n" + fast.stdout)
        for (a, da), (b, db) in zip(pn, fn):
            tol = max(0.01 * max(abs(a), abs(b)), 10.0 ** -min(da, db) * 1.001)
            self.assertLessEqual(abs(a - b), tol, f"{a} vs {b}\n{pillow.stdout}\n---\n{fast.stdout}")
        return pillow, fast

    def blend_inputs(self, shift):
        base = texture((240, 180), 7); base.save(self.project / "base.png")
        patch = base.crop((60, 40, 180, 140)).point(lambda v: min(255, v + shift))
        ImageDraw.Draw(patch).ellipse((35, 30, 85, 70), fill=(30, 160, 90)); patch.save(self.project / "patch.png")
        m = Image.new("L", (240, 180), 0); ImageDraw.Draw(m).ellipse((90, 65, 150, 115), fill=255); m.save(self.project / "mask.png")

    def test_blend_parity_and_identical_output(self):
        for shift, extra in ((12, []), (0, ["--no-match"]), (60, ["--no-match", "--feather", "3"])):
            self.blend_inputs(shift)
            args = ["blend", "--base", "base.png", "--patch", "patch.png", "--mask", "mask.png", "--at", "60,40", "--no-align-check"]
            pillow = self.run_cli(*args, *extra, "--engine", "pillow", "--out", "p.png")
            self.assertIn("Ring dE2000", pillow.stdout); self.assertIn("seam_step", pillow.stdout)
            self.assertNotIn("seam_grad", pillow.stdout)
            p_bytes = (self.project / "p.png").read_bytes()
            _, fast = self.both(*args, *extra, "--out", "o.png")
            if fast is not None:
                self.assertEqual((self.project / "p.png").read_bytes(), p_bytes)
                self.assertEqual(Image.open(self.project / "o.png").tobytes(), Image.open(self.project / "p.png").tobytes())

    def test_blend_color_mismatch_parity(self):
        base = texture((240, 180), 3); base.save(self.project / "base.png")
        texture((120, 100), 99).save(self.project / "patch.png")  # unrelated content: the ring cannot match
        m = Image.new("L", (240, 180), 0); m.paste(255, (90, 65, 150, 115)); m.save(self.project / "mask.png")
        pillow, _ = self.both("blend", "--base", "base.png", "--patch", "patch.png", "--mask", "mask.png", "--at", "60,40",
                              "--no-align-check", "--out", "o.png")
        self.assertEqual(pillow.returncode, 1); self.assertIn("color mismatch", pillow.stdout)

    def test_edit_check_parity(self):
        a = texture((200, 150), 5); a.save(self.project / "a.png")
        m = Image.new("L", (200, 150), 0); ImageDraw.Draw(m).ellipse((60, 40, 140, 110), fill=255); m.save(self.project / "m.png")
        inside = a.copy(); ImageDraw.Draw(inside).ellipse((70, 50, 130, 100), fill=(255, 255, 0)); inside.save(self.project / "in.png")
        leak = inside.copy(); ImageDraw.Draw(leak).rectangle((5, 5, 30, 30), fill=(0, 0, 255)); leak.save(self.project / "leak.png")
        for after, code in (("in.png", 0), ("leak.png", 1)):
            for extra in (["--mask", "m.png"], ["--mask", "m.png", "--edge", "3"], ["--bbox", "60,40,140,110"]):
                pillow, _ = self.both("edit-check", "--before", "a.png", "--after", after, *extra, "--out", "v.png")
                self.assertEqual(pillow.returncode, code, (after, extra, pillow.stdout))

    def test_shape_check_parity(self):
        def mask(name, box, size=(200, 160)):
            m = Image.new("L", size, 0); ImageDraw.Draw(m).ellipse(box, fill=255); m.save(self.project / name)
        mask("a.png", (40, 30, 160, 130)); mask("b.png", (41, 30, 161, 131)); mask("c.png", (44, 30, 164, 130))
        mask("far1.png", (10, 10, 30, 30), (1300, 60)); mask("far2.png", (1250, 10, 1270, 30), (1300, 60))
        for before, after, extra, code in (("a.png", "a.png", [], 0), ("a.png", "b.png", ["--max-iou-loss", "0.05"], 0),
                                           ("a.png", "b.png", [], 1), ("a.png", "c.png", [], 1), ("far1.png", "far2.png", [], 1)):
            pillow, _ = self.both("shape-check", "--before-mask", before, "--after-mask", after, *extra)
            self.assertEqual(pillow.returncode, code, (before, after, pillow.stdout))

    def draw_sword(self, name, pommel, guard, tip, bow=0):
        img = Image.new("RGB", (894, 1759), (20, 40, 150))
        d = ImageDraw.Draw(img)
        d.line((pommel, guard), fill=(110, 70, 40), width=26)
        dx, dy = tip[0] - guard[0], tip[1] - guard[1]
        n = (dx * dx + dy * dy) ** 0.5
        px, py = -dy / n, dx / n
        for i in range(40):
            a, b = i / 40, (i + 1) / 40
            off = lambda t: bow * 4 * t * (1 - t)
            d.line(((guard[0] + dx * a + px * off(a), guard[1] + dy * a + py * off(a)),
                    (guard[0] + dx * b + px * off(b), guard[1] + dy * b + py * off(b))),
                   fill=(225, 228, 235) if i % 2 else (160, 165, 178), width=max(4, round(44 * (1 - a * 0.8))))
        img.save(self.project / name)

    def test_axis_check_parity(self):
        self.draw_sword("ok.png", (100, 100), (300, 433), (700, 1100))
        self.draw_sword("hilt.png", (60, 230), (300, 433), (700, 1100))
        self.draw_sword("bow.png", (100, 100), (300, 433), (700, 1100), bow=70)
        for name, pts, code in (("ok.png", ["100,100", "300,433", "330,483", "700,1100"], 0),
                                ("hilt.png", ["60,230", "300,433", "330,483", "700,1100"], 1),
                                ("bow.png", ["100,100", "300,433", "700,1100"], 1)):
            pillow, fast = self.both("axis-check", "--image", name, "--points", *pts)
            self.assertEqual(pillow.returncode, code, (name, pillow.stdout))

    def test_axis_check_same_tilt_with_stray_trace_samples(self):
        # review 2.22: a Huber fit on the fast engine read 0.0 deg (exit 0) where Pillow's least squares read 0.5 deg (exit 1)
        Image.new("RGB", (900, 1200), (0, 0, 0)).save(self.project / "blank.png")
        spine = [(462.0 if i < 10 else 450.0, float(y), 20) for i, y in enumerate(range(300, 1100, 8))]
        mod = load_module()
        mod.trace_blade = lambda *a: spine
        results = {}
        for engine in ("pillow", "fast"):
            if engine == "fast" and not FAST: continue
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = mod.main(["axis-check", "--image", str(self.project / "blank.png"), "--points", "450,100", "450,700",
                                 "450,1100", "--engine", engine, "--max-offset", "20", "--max-bend", "0.3"])
            results[engine] = (code, re.search(r"([\d.]+) deg against it", out.getvalue()).group(1))
        self.assertEqual(results["pillow"], (1, "0.5"))
        if FAST: self.assertEqual(results["fast"], results["pillow"])

    def test_mask_from_diff_parity_without_small_components(self):
        a = texture((200, 150), 11); a.save(self.project / "a.png")
        b = a.copy(); ImageDraw.Draw(b).rectangle((50, 40, 90, 80), fill=(255, 0, 255)); b.save(self.project / "b.png")
        self.both("mask-from-diff", "--before", "a.png", "--after", "b.png", "--out", "p.png")
        pillow = self.run_cli("mask-from-diff", "--before", "a.png", "--after", "b.png", "--out", "q.png", "--engine", "pillow")
        self.assertEqual(pillow.returncode, 0, pillow.stdout + pillow.stderr)
        try:
            import numpy, cv2  # noqa: F401
        except ImportError:
            return
        self.assertEqual(Image.open(self.project / "p.png").tobytes(), Image.open(self.project / "q.png").tobytes())


    def test_mask_from_diff_specks_same_verdict_and_mask_with_default_flags(self):
        # review 2.22: specks only -> Pillow wrote a 363 px mask (exit 0), fast dropped them (exit 1)
        a = texture((200, 150), 13); a.save(self.project / "a.png")
        b = a.copy()
        for x, y in ((5, 5), (50, 50), (150, 100)): b.putpixel((x, y), tuple(0 if c > 127 else 255 for c in a.getpixel((x, y))))
        b.save(self.project / "specks.png")
        pillow, _ = self.both("mask-from-diff", "--before", "a.png", "--after", "specks.png", "--out", "s.png")
        self.assertEqual(pillow.returncode, 1, pillow.stdout); self.assertIn("dropped 3 under 16 px", pillow.stdout)
        self.assertFalse((self.project / "s.png").exists())
        # specks plus a real change, with an L-shaped and a diagonal component: both engines keep exactly the same pixels
        d = ImageDraw.Draw(b)
        d.rectangle((60, 40, 99, 79), fill=(255, 255, 255)); d.line((120, 10, 140, 30), fill=(255, 0, 255), width=1)
        d.rectangle((170, 120, 172, 124), fill=(0, 255, 255))  # 15 px: dropped
        b.save(self.project / "mixed.png")
        self.ok("mask-from-diff", "--before", "a.png", "--after", "mixed.png", "--out", "mp.png", "--engine", "pillow", "--grow", "0")
        if FAST:
            self.both("mask-from-diff", "--before", "a.png", "--after", "mixed.png", "--out", "mf.png", "--grow", "0")
            self.assertEqual(Image.open(self.project / "mp.png").tobytes(), Image.open(self.project / "mf.png").tobytes())


class MaskFromDiffTests(StudioBase):
    """mask-from-diff: changed pixels (a channel differs by more than --threshold), grown, small components dropped."""

    def setUp(self):
        super().setUp()
        self.a = texture((200, 150), 21); self.a.save(self.project / "a.png")
        b = self.a.copy(); ImageDraw.Draw(b).rectangle((60, 40, 99, 79), fill=(255, 255, 255)); b.save(self.project / "b.png")

    def test_mask_is_the_grown_change(self):
        for engine in ("pillow", "auto"):
            run = self.ok("mask-from-diff", "--before", "a.png", "--after", "b.png", "--out", f"m-{engine}.png", "--engine", engine)
            m = Image.open(self.project / f"m-{engine}.png")
            self.assertEqual(m.mode, "L"); self.assertEqual({v for _, v in m.getcolors()}, {0, 255})
            self.assertEqual(m.getbbox(), (55, 35, 105, 85))  # the 40x40 change grown 5 px on every side
            self.assertIn("box 55,35,105,85", run.stdout)
        run = self.ok("mask-from-diff", "--before", "a.png", "--after", "b.png", "--out", "g0.png", "--grow", "0")
        self.assertEqual(Image.open(self.project / "g0.png").getbbox(), (60, 40, 100, 80))

    def test_change_at_or_under_threshold_is_no_change(self):
        faint = self.a.point(lambda v: min(255, v + 20)); faint.save(self.project / "faint.png")
        run = self.run_cli("mask-from-diff", "--before", "a.png", "--after", "faint.png", "--out", "m.png")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("no change", run.stdout); self.assertFalse((self.project / "m.png").exists())
        run = self.ok("mask-from-diff", "--before", "a.png", "--after", "faint.png", "--out", "m.png", "--threshold", "10")
        self.assertTrue((self.project / "m.png").exists())

    def test_small_components_are_dropped_on_both_engines(self):
        b = Image.open(self.project / "b.png").copy()
        for x in range(10, 190, 30):  # single-pixel noise far from the real change, every channel moved by 128 or more
            b.putpixel((x, 140), tuple(0 if c > 127 else 255 for c in self.a.getpixel((x, 140))))
        b.save(self.project / "noisy.png")
        for engine in ("pillow", "fast") if FAST else ("pillow",):
            run = self.ok("mask-from-diff", "--before", "a.png", "--after", "noisy.png", "--out", f"f-{engine}.png", "--engine", engine)
            self.assertIn("dropped 6 under 16 px", run.stdout)
            self.assertEqual(Image.open(self.project / f"f-{engine}.png").getbbox(), (55, 35, 105, 85))
            run = self.ok("mask-from-diff", "--before", "a.png", "--after", "noisy.png", "--out", f"k-{engine}.png", "--engine", engine,
                          "--min-area", "0")
            self.assertEqual(Image.open(self.project / f"k-{engine}.png").getbbox()[3], 146)  # the noise row, grown, is kept

    def test_bad_input_exit_2(self):
        Image.new("RGB", (10, 10)).save(self.project / "small.png")
        for extra in (["--out", "a.png"], ["--out", "b.png"], ["--out", "m.jpg"], ["--out", "nodir/m.png"], ["--out", "m.png", "--threshold", "300"],
                      ["--out", "m.png", "--grow", "-1"], ["--out", "m.png", "--min-area", "-2"]):
            run = self.run_cli("mask-from-diff", "--before", "a.png", "--after", "b.png", *extra)
            self.assertEqual(run.returncode, 2, (extra, run.stdout, run.stderr))
        run = self.run_cli("mask-from-diff", "--before", "a.png", "--after", "small.png", "--out", "m.png")
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr); self.assertIn("size differs", run.stderr)
        self.assertFalse((self.project / "m.png").exists())
        self.assertEqual(Image.open(self.project / "a.png").tobytes(), self.a.tobytes())


@needs_fast
class AutoAlignTests(StudioBase):
    """align-check --auto finds the patch position with OpenCV template matching and writes it into align.json."""

    def setUp(self):
        super().setUp()
        self.base = texture((420, 320), 31); self.base.save(self.project / "base.png")

    def auto(self, *extra, patch="patch.png", out="al"):
        return self.run_cli("align-check", "--base", "base.png", "--patch", patch, "--auto", "--out-dir", out, *extra)

    def test_found_within_one_pixel_for_perturbed_crops(self):
        for i, (dx, dy) in enumerate(((0, 0), (-40, 17), (23, -40), (40, 40), (-13, -29))):
            x, y = 150 + dx, 110 + dy
            self.base.crop((x, y, x + 120, y + 90)).save(self.project / "patch.png")
            run = self.auto(out=f"al{i}")
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            at = json.loads((self.project / f"al{i}/align.json").read_text())["at"]
            self.assertLessEqual(max(abs(at[0] - x), abs(at[1] - y)), 1, (dx, dy, at, run.stdout))
            self.assertIn("scale 1.00", run.stdout)

    def test_masked_patch_matches_its_context_and_flows_into_blend(self):
        x, y = 170, 95
        patch = self.base.crop((x, y, x + 140, y + 110))
        ImageDraw.Draw(patch).ellipse((40, 30, 100, 80), fill=(250, 20, 20)); patch.save(self.project / "patch.png")
        m = Image.new("L", (420, 320), 0); ImageDraw.Draw(m).ellipse((x + 40, y + 30, x + 100, y + 80), fill=255); m.save(self.project / "mask.png")
        run = self.auto("--mask", "mask.png")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("context outside the mask", run.stdout)
        self.assertEqual(json.loads((self.project / "al/align.json").read_text())["at"], [x, y])
        self.ok("align-check", "--base", "base.png", "--patch", "patch.png", "--auto", "--mask", "mask.png", "--out-dir", "al", "--accept")
        run = self.ok("blend", "--base", "base.png", "--patch", "patch.png", "--mask", "mask.png", "--at", f"{x},{y}",
                      "--align", "al/align.json", "--out", "o.png")
        self.assertIn("Registration: accepted", run.stdout)

    def test_unrelated_patch_is_no_reliable_match(self):
        texture((120, 90), 77).save(self.project / "other.png")
        run = self.auto(patch="other.png")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("no reliable match", run.stdout); self.assertIn("give --at", run.stdout)
        self.assertFalse((self.project / "al").exists())

    def test_repeated_motif_is_ambiguous(self):
        twin = self.base.copy(); twin.paste(self.base.crop((20, 20, 140, 110)), (280, 210)); twin.save(self.project / "base.png")
        twin.crop((20, 20, 140, 110)).save(self.project / "patch.png")
        run = self.auto()
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("matches as well", run.stdout); self.assertFalse((self.project / "al").exists())

    def test_flat_patch_or_flat_context_is_refused(self):
        # review 2.22: a flat template scores 1.0 everywhere, so it was "found" (or blamed on a repeat or a 1.06 scale)
        flat = self.base.copy(); ImageDraw.Draw(flat).rectangle((10, 10, 120, 100), fill=(50, 60, 70)); flat.save(self.project / "base.png")
        Image.new("RGB", (40, 30), (50, 60, 70)).save(self.project / "flat.png")
        run = self.auto(patch="flat.png")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("no reliable match: the patch is flat", run.stdout); self.assertFalse((self.project / "al").exists())
        # a textured island in a flat area, masked: the context left to match is flat
        flat.paste(texture((40, 30), 3), (60, 50)); flat.save(self.project / "base.png")
        flat.crop((25, 20, 115, 95)).save(self.project / "ctx.png")
        m = Image.new("L", (420, 320), 0); m.paste(255, (60, 50, 100, 80)); m.save(self.project / "mask.png")
        run = self.auto("--mask", "mask.png", patch="ctx.png", out="al2")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("context outside the mask is flat", run.stdout); self.assertFalse((self.project / "al2").exists())

    def test_tied_scores_prefer_scale_one_and_grow_runs_once(self):
        mod = load_module()
        np, cv2 = mod.accel.modules()
        real, calls = cv2.matchTemplate, []
        grow = mod.grow
        mod.grow = lambda *a: calls.append(a) or grow(*a)
        cv2.matchTemplate = lambda img, templ, method, mask=None: np.ones(
            (img.shape[0] - templ.shape[0] + 1, img.shape[1] - templ.shape[1] + 1), np.float32)  # every place and scale ties
        try:
            hard = Image.new("L", (420, 320), 0); hard.paste(255, (190, 140, 230, 170))
            found = mod.auto_place(self.base, self.base.crop((150, 110, 270, 200)), hard)
        finally:
            cv2.matchTemplate = real
        self.assertEqual(found[2], 1.0, found)
        self.assertEqual(len(calls), 1)

    def test_scaled_patch_must_be_resized_not_silently_fixed(self):
        crop = self.base.crop((150, 110, 270, 200))
        crop.resize((round(120 / 1.06), round(90 / 1.06)), Image.LANCZOS).save(self.project / "small.png")
        run = self.auto(patch="small.png")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("must be resized", run.stdout)
        self.assertAlmostEqual(float(re.search(r"scale (\d\.\d\d)", run.stdout).group(1)), 1.06, delta=0.015)
        self.assertFalse((self.project / "al").exists())

    def test_auto_and_at_together_exit_2(self):
        self.base.crop((150, 110, 270, 200)).save(self.project / "patch.png")
        run = self.auto("--at", "150,110")
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)


@needs_fast
class SeamGradTests(StudioBase):
    def test_seam_grad_reports_a_hard_seam(self):
        base = Image.new("RGB", (160, 120), (120, 120, 120)); base.save(self.project / "base.png")
        Image.new("RGB", (60, 40), (200, 200, 200)).save(self.project / "patch.png")
        m = Image.new("L", (160, 120), 0); m.paste(255, (50, 40, 110, 80)); m.save(self.project / "m.png")
        run = self.run_cli("blend", "--base", "base.png", "--patch", "patch.png", "--mask", "m.png", "--at", "50,40",
                           "--no-align-check", "--no-match", "--feather", "0", "--out", "o.png")
        line = [ln for ln in run.stdout.splitlines() if ln.startswith("seam_grad:")]
        self.assertEqual(len(line), 1, run.stdout)
        out, base_val = (float(v) for v in re.findall(r"\d+\.\d+", line[0])[:2])
        self.assertGreater(out, 100); self.assertEqual(base_val, 0.0)
        self.assertIn(run.returncode, (0, 1))


if __name__ == "__main__":
    unittest.main()
