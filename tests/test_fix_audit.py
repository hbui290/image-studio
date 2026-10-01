"""Regression tests for the v2.2 audit fixes. Run: python -m unittest discover -s tests"""

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

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/image-studio/skills/image-verify/scripts"
AUDIT, BRIEF = SCRIPTS / "audit_candidate.py", SCRIPTS / "contract_to_brief.py"
SIZE = (64, 48)


class AuditFixes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, value):
        path = self.dir / name
        path.write_text(json.dumps(value) if not isinstance(value, str) else value, encoding="utf-8")
        return path

    def contract(self, check_id="C1", fmt="PNG", locked=True, **canvas):
        return self.write("contract.json", {
            "version": 1, "mode": "repair", "intent": "Fix the square",
            "canvas": {"width": SIZE[0], "height": SIZE[1], "format": fmt, **canvas},
            "targets": [{"id": "A", "name": "square", "bbox": [0, 0, 20, 20]}],
            "checks": [{"id": check_id, "target_id": "A", "kind": "change", "requirement": "Square is fixed"}],
            "pixel_lock_outside_mask": locked})

    def review(self, check_id="C1", **extra):
        return self.write("review.json", {"reviewer": "t", "results": [
            {"id": check_id, "status": "pass", "evidence": "looked", **extra}]})

    def images(self, size=SIZE, change=((0, 0, 19, 19), "blue")):
        Image.new("RGB", SIZE, "gray").save(self.dir / "source.png")
        candidate = Image.new("RGB", size, "gray")
        if change:
            ImageDraw.Draw(candidate).rectangle(change[0], fill=change[1])
        candidate.save(self.dir / "candidate.png")
        mask = Image.new("L", SIZE, 0)
        ImageDraw.Draw(mask).rectangle((0, 0, 19, 19), fill=255)
        mask.save(self.dir / "mask.png")

    def audit(self, *extra, out="out", mask=True):
        cmd = [sys.executable, str(AUDIT), "--contract", str(self.dir / "contract.json"), "--source",
               str(self.dir / "source.png"), "--candidate", str(self.dir / "candidate.png"),
               "--review", str(self.dir / "review.json"), "--out", str(self.dir / out), *extra]
        if mask:
            cmd += ["--mask", str(self.dir / "mask.png")]
        return subprocess.run(cmd, capture_output=True, text=True)

    def decision(self, out="out"):
        return json.loads((self.dir / out / "decision.json").read_text())

    def test_wrong_size_candidate_with_mask_is_rejected_not_a_command_error(self):
        self.images(size=(32, 24)), self.contract(), self.review()
        run = self.audit()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.decision()["action"], "reject_technical")

    def test_invisible_change_is_held_not_accepted(self):
        self.images(change=((0, 0, 0, 0), (129, 128, 128))), self.contract(), self.review()
        self.assertEqual(self.audit().returncode, 0)
        decision = self.decision()
        self.assertEqual(decision["action"], "hold_for_inspection")
        self.assertIn("C1", decision["barely_visible_change_pixels"])

    def test_confirmed_small_change_is_accepted(self):
        self.images(change=((0, 0, 0, 0), "black")), self.contract(), self.review(visible_change_confirmed=True)
        self.assertEqual(self.audit().returncode, 0)
        self.assertEqual(self.decision()["action"], "accepted_by_checks")

    def test_real_change_is_still_accepted(self):
        self.images(), self.contract(), self.review()
        self.assertEqual(self.audit().returncode, 0)
        self.assertEqual(self.decision()["action"], "accepted_by_checks")

    def test_ids_with_surrounding_whitespace_are_refused(self):
        self.images(), self.contract(check_id=" C1 "), self.review(check_id=" C1 ")
        run = self.audit()
        self.assertEqual(run.returncode, 2)
        self.assertIn("whitespace", run.stderr)

    def test_animated_candidate_is_rejected(self):
        self.images(), self.contract(fmt="GIF"), self.review()
        frames = [Image.new("RGB", SIZE, "gray"), Image.new("RGB", SIZE, "black")]
        ImageDraw.Draw(frames[0]).rectangle((0, 0, 19, 19), fill="blue")
        frames[0].save(self.dir / "candidate.png", format="GIF", save_all=True, append_images=frames[1:])
        self.assertEqual(self.audit(mask=False, out="o2").returncode, 2)  # lock requires a mask
        self.contract(fmt="GIF", locked=False)
        self.assertEqual(self.audit(mask=False).returncode, 0)
        self.assertIn("animated", " ".join(self.decision()["issues"]))

    def test_16bit_rgb_tiff_is_refused(self):
        self.contract(fmt="TIFF"), self.review()
        # Minimal uncompressed 16-bit RGB TIFF: Pillow decodes it to 8-bit RGB.
        width, height = SIZE
        pixels = b"\x10\x00" * 3 * width * height
        entries = [(256, 3, 1, width), (257, 3, 1, height), (258, 3, 3, 8 + 12 * 12 + 4 + 6),
                   (259, 3, 1, 1), (262, 3, 1, 2), (273, 4, 1, 0), (277, 3, 1, 3), (278, 3, 1, height),
                   (279, 4, 1, len(pixels)), (284, 3, 1, 1)]
        ifd_size = 2 + 12 * len(entries) + 4
        bits_offset, data_offset = 8 + ifd_size, 8 + ifd_size + 6
        blob = bytearray(b"II*\x00" + (8).to_bytes(4, "little") + len(entries).to_bytes(2, "little"))
        for tag, kind, count, value in entries:
            value = bits_offset if tag == 258 else data_offset if tag == 273 else value
            blob += tag.to_bytes(2, "little") + kind.to_bytes(2, "little") + count.to_bytes(4, "little")
            blob += value.to_bytes(4, "little") if kind == 4 or tag == 258 else value.to_bytes(2, "little") + b"\0\0"
        blob += b"\0\0\0\0" + (16).to_bytes(2, "little") * 3 + pixels
        for name in ("source.png", "candidate.png"):
            (self.dir / name).write_bytes(bytes(blob))
        with Image.open(self.dir / "source.png") as opened:
            self.assertEqual((opened.format, opened.mode), ("TIFF", "RGB"))
        Image.new("L", SIZE, 255).save(self.dir / "mask.png")
        self.assertEqual(self.audit().returncode, 0)
        self.assertIn("16 bits per color channel", " ".join(self.decision()["issues"]))

    def test_alpha_required_rejects_opaque_candidate(self):
        self.images(), self.contract(alpha_required=True), self.review()
        self.assertEqual(self.audit().returncode, 0)
        self.assertIn("transparent", " ".join(self.decision()["issues"]))

    def test_bom_json_is_accepted_and_lone_surrogate_writes_nothing(self):
        self.images(), self.review()
        text = json.dumps(json.loads(self.contract().read_text()))
        self.write("contract.json", "﻿" + text)
        self.assertEqual(self.audit().returncode, 0)
        self.write("review.json", '{"results": [{"id": "C1", "status": "fail", "evidence": "\\ud800"}]}')
        run = self.audit(out="bad")
        self.assertEqual(run.returncode, 2)
        self.assertFalse((self.dir / "bad").exists())

    def test_canvas_format_must_be_a_decoded_format_name(self):
        self.images(), self.review()
        for fmt, hint in (("PNG ", "canvas.format"), ("JPG", "JPEG")):
            self.contract(fmt=fmt)
            run = self.audit(out="o-" + fmt.strip())
            self.assertEqual(run.returncode, 2, run.stderr)
            self.assertIn(hint, run.stderr)
            self.assertNotIn("Traceback", run.stderr)

    def test_deep_json_is_a_clean_error(self):
        self.images(), self.review()
        self.write("contract.json", "[" * 100000 + "]" * 100000)
        run = self.audit()
        self.assertEqual(run.returncode, 2)
        self.assertNotIn("Traceback", run.stderr)

    def test_brief_keeps_every_format_and_contract_alpha(self):
        self.contract(fmt="TIFF", alpha_required=True)
        run = subprocess.run([sys.executable, str(BRIEF), str(self.dir / "contract.json"),
                              "--out", str(self.dir / "brief.json")], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        checks = json.loads((self.dir / "brief.json").read_text())["file_checks"]
        self.assertEqual((checks["format"], checks["alpha_required"]), ("TIFF", True))

    def test_brief_missing_output_folder_is_a_clean_error(self):
        self.contract()
        run = subprocess.run([sys.executable, str(BRIEF), str(self.dir / "contract.json"),
                              "--out", str(self.dir / "no/such/brief.json")], capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        self.assertNotIn("Traceback", run.stderr)


if __name__ == "__main__":
    unittest.main()
