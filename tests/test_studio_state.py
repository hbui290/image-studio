"""Project memory, evidence gate, preferences, and hooks (studio_state.py).

Every test runs in a temp dir with IMAGE_STUDIO_HOME pointing at a temp dir, so the real
~/.image-studio is never touched.
"""

import ast
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    raise unittest.SkipTest("Pillow is not installed")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/image-studio/skills/image-verify/scripts/studio_state.py"
CARD = (120, 40, 170, 110)  # the "dragon card" the user asked to remove (Oct 16-17)
LOGO_BOX = [20, 20, 80, 80]  # where the logo sits in the poster
DOTS = ([2, 2, 22, 22], [20, 120, 40, 140], [170, 5, 190, 25])  # D1-D3: small artifacts fixed earlier


def load_module():
    spec = importlib.util.spec_from_file_location("studio_state_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def draw_logo(size=60, star=True, shift=0):
    """Transparent logo: a thick 'D'-like stroke plus an optional separate black star."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((4 + shift, 4, 14 + shift, 55), fill=(20, 20, 160, 255))
    draw.rectangle((4 + shift, 4, 40 + shift, 12), fill=(20, 20, 160, 255))
    draw.rectangle((4 + shift, 47, 40 + shift, 55), fill=(20, 20, 160, 255))
    draw.rectangle((32 + shift, 4, 40 + shift, 55), fill=(20, 20, 160, 255))
    if star:
        draw.polygon([(48, 24), (52, 32), (56, 24), (52, 16)], fill=(0, 0, 0, 255))
    return img


class StudioBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.home = base / "home"
        self.project = base / "project"
        self.project.mkdir()
        self.store = self.project / ".image-studio"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, stdin=None, cwd=None, home=None, env_extra=None):
        env = dict(os.environ, IMAGE_STUDIO_HOME=str(home or self.home), **(env_extra or {}))
        run = subprocess.run([sys.executable, str(SCRIPT)] + [str(a) for a in args], input=stdin,
                             capture_output=True, text=True, cwd=str(cwd or self.project), env=env)
        self.assertNotIn("Traceback", run.stderr, run.stderr)
        self.assertNotIn("Traceback", run.stdout, run.stdout)
        return run

    def ok(self, *args, **kw):
        run = self.run_cli(*args, **kw)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return run

    def init(self, brand="acme"):
        return self.ok("init", "--project", self.project, "--brand", brand)

    def poster(self, name="poster.png", card=True, logo=None, logo_offset=(0, 0), dots=False):
        img = Image.new("RGB", (200, 150), (255, 255, 255))
        if card:
            ImageDraw.Draw(img).rectangle(CARD, fill=(200, 30, 30))
        if dots:
            for x0, y0, x1, y1 in DOTS:
                ImageDraw.Draw(img).rectangle((x0 + 3, y0 + 3, x1 - 3, y1 - 3), fill=(0, 0, 0))
        if logo is not None:
            img.paste(logo, (LOGO_BOX[0] + logo_offset[0], LOGO_BOX[1] + logo_offset[1]), logo)
        path = self.project / name
        img.save(path)
        return path

    def approve_poster(self, path):
        return self.ok("approve", "deliverable", "--name", "poster", "--file", path, "--width", 200,
                       "--height", 150, "--alpha", "any", "--format", "PNG")

    def defect(self, bbox, kind="scope", note="x", source="user"):
        args = ["defect", "add", "--deliverable", "poster", "--bbox", ",".join(map(str, bbox)),
                "--kind", kind, "--source", source, "--note", note]
        return self.ok(*args).stdout.strip().split()[-1]

    def gate(self, *extra):
        return self.run_cli("gate", "--deliverable", "poster", *extra)

    @staticmethod
    def run_id(run):
        for line in run.stdout.splitlines():
            if line.startswith("Run: "):
                return line.split()[1]
        raise AssertionError("no run id in gate output:\n" + run.stdout)

    def run_dir(self, run_id):
        return self.store / "gate" / run_id

    def defects(self):
        return [json.loads(l) for l in (self.store / "defects.jsonl").read_text().splitlines() if l.strip()]

    def state(self):
        return json.loads((self.store / "state.json").read_text())


class StoreTests(StudioBase):
    def test_init_creates_store_and_prints_path(self):
        run = self.init()
        self.assertIn(str(self.store), run.stdout)
        state = self.state()
        self.assertEqual(state["brand"], "acme")
        self.assertEqual(state["schema_version"], 1)
        for key in ("deliverables", "decisions"):
            self.assertIn(key, state)
        self.assertTrue((self.store / "defects.jsonl").is_file())

    def test_commands_without_store_exit_2(self):
        for args in (["brief"], ["gate", "--deliverable", "poster"], ["defect", "close", "--id", "D1",
                     "--status", "resolved", "--note", "n"]):
            run = self.run_cli(*args)
            self.assertEqual(run.returncode, 2, args)
            self.assertIn("init", run.stderr)

    def test_store_is_found_from_a_subfolder(self):
        self.init()
        sub = self.project / "work" / "round2"
        sub.mkdir(parents=True)
        self.assertIn("acme", self.ok("brief", cwd=sub).stdout)

    def test_home_preferences_dir_is_never_a_project_store(self):
        user = Path(self.tmp.name) / "user"
        home = user / ".image-studio"
        self.ok("pref", "add", "--rule", "Minimal style", "--check", "count elements", home=home)
        (home / "state.json").write_text(json.dumps({"brand": "x", "deliverables": {}, "masters": {},
                                                      "decisions": []}))
        run = self.run_cli("brief", cwd=user, home=home)
        self.assertEqual(run.returncode, 2)
        run = self.run_cli("init", "--project", user, "--brand", "x", home=home)
        self.assertEqual(run.returncode, 2)

    def test_bad_input_exits_2(self):
        self.init()
        path = self.poster()
        cases = [
            ["approve", "deliverable", "--name", "poster", "--file", self.project / "missing.png",
             "--width", 200, "--height", 150, "--format", "PNG"],
            ["approve", "deliverable", "--name", "bad name!", "--file", path, "--width", 200, "--height", 150,
             "--format", "PNG"],
            ["defect", "add", "--deliverable", "nope", "--bbox", "1,1,5,5", "--kind", "scope", "--note", "x"],
            ["defect", "close", "--id", "D99", "--status", "resolved", "--note", "x"],
            ["gate", "--deliverable", "nope"],
            ["verdict", "--run", "nope", "--id", "D1", "--status", "pass", "--evidence", "looked at it closely"],
            ["init", "--project", self.project, "--brand", "other"],
        ]
        for args in cases:
            run = self.run_cli(*args)
            self.assertEqual(run.returncode, 2, (args, run.stdout, run.stderr))
            self.assertTrue(run.stderr.strip(), args)
        self.approve_poster(path)
        for bbox in ("5,5,1,1", "1,2,3", "0,0,999,10", "a,b,c,d"):
            run = self.run_cli("defect", "add", "--deliverable", "poster", "--bbox", bbox, "--kind", "scope",
                               "--note", "x")
            self.assertEqual(run.returncode, 2, bbox)

    def test_corrupt_state_is_a_clean_error(self):
        self.init()
        (self.store / "state.json").write_text("{not json")
        run = self.run_cli("brief")
        self.assertEqual(run.returncode, 2)
        self.assertIn("state.json", run.stderr)

    def test_defect_ids_are_stable_and_close_keeps_history(self):
        self.init()
        self.approve_poster(self.poster())
        self.assertEqual(self.defect([1, 1, 20, 20]), "D1")
        self.assertEqual(self.defect([1, 1, 20, 20]), "D2")
        self.ok("defect", "close", "--id", "D1", "--status", "resolved", "--note", "fixed seam")
        self.assertEqual(self.defect([1, 1, 20, 20]), "D3")
        d1 = self.defects()[0]
        self.assertEqual(d1["status"], "resolved")
        self.assertEqual(d1["source"], "user")
        self.assertGreaterEqual(len(d1["history"]), 2)


class Oct17Tests(StudioBase):
    """Recreate the Oct 17 failure: an open defect (dragon card) shipped as 'done'."""

    def setUp(self):
        super().setUp()
        self.init()
        self.approve_poster(self.poster(dots=True))
        for box in DOTS:
            self.defect(box, kind="artifact")
        self.path = self.poster()  # dots fixed, dragon card still there
        self.approve_poster(self.path)
        for i in (1, 2, 3):
            self.ok("defect", "close", "--id", f"D{i}", "--status", "resolved", "--note", "fixed earlier")
        self.assertEqual(self.defect(list(CARD), note="remove the dragon card"), "D4")

    def pass_all(self, run_id, ids=("D1", "D2", "D3", "D4")):
        for defect_id in ids:
            self.ok("verdict", "--run", run_id, "--id", defect_id, "--status", "pass",
                    "--evidence", f"{defect_id} inspected at 100% and 200%, region is clean")

    def test_open_defect_blocks_gate(self):
        run = self.gate()
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertIn("D4", run.stdout)
        self.assertIn("Still failing", run.stdout)
        self.assertIn("open", run.stdout)

    def test_regression_crops_cover_every_defect(self):
        run_dir = self.run_dir(self.run_id(self.gate()))
        checklist = json.loads((run_dir / "checklist.json").read_text())
        self.assertEqual(sorted(d["id"] for d in checklist["defects"]), ["D1", "D2", "D3", "D4"])
        for defect in checklist["defects"]:
            for scale in ("100", "200"):
                crop = run_dir / defect["crops"][scale]["file"]
                self.assertTrue(crop.is_file(), crop)
        d4 = next(d for d in checklist["defects"] if d["id"] == "D4")
        with Image.open(run_dir / d4["crops"]["100"]["file"]) as crop:
            self.assertEqual(crop.size, (CARD[2] - CARD[0] + 32, CARD[3] - CARD[1] + 32))
            self.assertEqual(crop.convert("RGB").getpixel((30, 30)), (200, 30, 30))  # the card is still there
        with Image.open(run_dir / d4["crops"]["200"]["file"]) as crop:
            self.assertEqual(crop.size, ((CARD[2] - CARD[0] + 32) * 2, (CARD[3] - CARD[1] + 32) * 2))

    def test_closed_but_fabricated_verdict_is_rejected(self):
        self.ok("defect", "close", "--id", "D4", "--status", "resolved", "--note", "removed the card")
        run_id = self.run_id(self.gate())
        self.pass_all(run_id, ("D1", "D2", "D3"))
        verdicts_path = self.run_dir(run_id) / "verdicts.json"
        verdicts = json.loads(verdicts_path.read_text())
        verdicts["verdicts"]["D4"] = {"status": "pass", "crop_sha256": "0" * 64,
                                      "evidence": "checked logo, frame, corners", "reviewer": "self"}
        verdicts_path.write_text(json.dumps(verdicts))
        run = self.gate("--run", run_id)
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertIn("D4", run.stdout)
        self.assertIn("crop", run.stdout.lower())

    def test_verdicts_from_an_older_run_are_rejected(self):
        self.ok("defect", "close", "--id", "D4", "--status", "resolved", "--note", "removed the card")
        old = self.run_id(self.gate())
        self.pass_all(old)
        new = self.run_id(self.gate())
        self.assertNotEqual(old, new)
        shutil.copy(self.run_dir(old) / "verdicts.json", self.run_dir(new) / "verdicts.json")
        run = self.gate("--run", new)
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertIn("another run", run.stdout)

    def test_missing_verdict_and_short_evidence_fail(self):
        self.ok("defect", "close", "--id", "D4", "--status", "resolved", "--note", "removed the card")
        run_id = self.run_id(self.gate())
        self.pass_all(run_id, ("D1", "D2", "D3"))
        run = self.gate("--run", run_id)
        self.assertEqual(run.returncode, 1)
        self.assertIn("Not checked", run.stdout)
        self.assertIn("D4", run.stdout)
        bad = self.run_cli("verdict", "--run", run_id, "--id", "D4", "--status", "pass", "--evidence", "ok")
        self.assertEqual(bad.returncode, 2)

    def test_fail_verdict_keeps_gate_failing(self):
        self.ok("defect", "close", "--id", "D4", "--status", "resolved", "--note", "removed the card")
        run_id = self.run_id(self.gate())
        self.pass_all(run_id, ("D1", "D2", "D3"))
        self.ok("verdict", "--run", run_id, "--id", "D4", "--status", "fail", "--evidence",
                "the red dragon card is still visible in the crop")
        run = self.gate("--run", run_id)
        self.assertEqual(run.returncode, 1)
        self.assertIn("Still failing", run.stdout)

    def test_correct_flow_passes_and_is_recorded(self):
        fixed = self.poster("poster-v2.png", card=False)
        self.approve_poster(fixed)
        self.ok("defect", "close", "--id", "D4", "--status", "resolved", "--note", "card removed in v2")
        run_id = self.run_id(self.gate())
        self.pass_all(run_id)
        run = self.gate("--run", run_id)
        self.assertEqual(run.returncode, 0, run.stdout)
        self.assertIn("Checked", run.stdout)
        gate = self.state()["gates"]["poster"]
        self.assertEqual(gate["run_id"], run_id)
        self.assertEqual(gate["sha256"], self.state()["deliverables"]["poster"]["current_sha256"])
        verdicts = json.loads((self.run_dir(run_id) / "verdicts.json").read_text())
        self.assertEqual(verdicts["run_id"], run_id)
        self.assertEqual(verdicts["verdicts"]["D4"]["reviewer"], "self")

    def test_gate_output_names_the_exact_next_commands(self):
        run = self.gate()
        run_id = self.run_id(run)
        self.assertIn("defect close --id D4", run.stdout)
        for defect_id in ("D1", "D2", "D3", "D4"):
            self.assertIn(f"verdict --run {run_id} --id {defect_id}", run.stdout)
        self.assertIn(f"gate --deliverable poster --run {run_id}", run.stdout)
        other = self.poster("poster-v2.png", card=False)
        run = self.gate("--file", other)
        self.assertIn(f"approve deliverable --name poster --file {other}", run.stdout)
        self.assertNotIn("verdict --run", run.stdout)

    def test_printed_commands_use_the_real_script_path(self):
        run = self.gate()
        self.assertIn(f"python3 {SCRIPT} verdict --run", run.stdout)
        self.assertNotIn("<skills>", run.stdout)
        block = self.run_cli("hook", "stop", stdin=json.dumps({"cwd": str(self.project), "session_id": "p",
                                                                "last_assistant_message": "Done."}))
        self.assertIn(f"python3 {SCRIPT} gate", json.loads(block.stdout)["reason"])
        self.assertNotIn("<skills>", block.stdout)
        missing = self.run_cli("brief", cwd=Path(self.tmp.name))
        self.assertIn(f"python3 {SCRIPT} init", missing.stderr)
        self.assertNotIn("<skills>", missing.stderr)
        spaced = Path(self.tmp.name) / "plugin dir" / "studio_state.py"
        spaced.parent.mkdir()
        shutil.copy(SCRIPT, spaced)
        run = subprocess.run([sys.executable, str(spaced), "gate", "--deliverable", "poster"], capture_output=True,
                             text=True, cwd=str(self.project), env=dict(os.environ, IMAGE_STUDIO_HOME=str(self.home)))
        self.assertIn(f"python3 '{spaced}' verdict --run", run.stdout)

    def test_file_changed_after_run_is_stale(self):
        self.ok("defect", "close", "--id", "D4", "--status", "resolved", "--note", "removed the card")
        run_id = self.run_id(self.gate())
        self.pass_all(run_id)
        self.poster(card=False)  # edited in place after the crops were made, not re-approved
        run = self.gate("--run", run_id)
        self.assertEqual(run.returncode, 1)
        self.assertIn("stale", run.stdout)
        self.assertIn("not the approved current file", run.stdout)

    def test_tampered_crop_is_rejected(self):
        self.ok("defect", "close", "--id", "D4", "--status", "resolved", "--note", "removed the card")
        run_id = self.run_id(self.gate())
        self.pass_all(run_id)
        checklist = json.loads((self.run_dir(run_id) / "checklist.json").read_text())
        d4 = next(d for d in checklist["defects"] if d["id"] == "D4")
        Image.new("RGB", (10, 10), "white").save(self.run_dir(run_id) / d4["crops"]["100"]["file"])
        run = self.gate("--run", run_id)
        self.assertEqual(run.returncode, 1)


class HashTests(StudioBase):
    def test_modified_file_is_not_the_approved_current_file_and_verdicts_go_stale(self):
        self.init()
        self.approve_poster(self.poster(card=False, dots=True))
        self.defect(DOTS[0])
        path = self.poster(card=False)
        self.approve_poster(path)
        self.ok("defect", "close", "--id", "D1", "--status", "resolved", "--note", "fixed")
        run_id = self.run_id(self.gate())
        self.ok("verdict", "--run", run_id, "--id", "D1", "--status", "pass",
                "--evidence", "corner seam is gone at 200%")
        self.assertEqual(self.gate("--run", run_id).returncode, 0)
        img = Image.open(path).convert("RGB")
        img.putpixel((100, 100), (0, 0, 0))
        img.save(path)
        run = self.gate()
        self.assertEqual(run.returncode, 1)
        self.assertIn("not the approved current file", run.stdout)
        self.approve_poster(path)  # approving the edit makes the old verdicts stale
        run = self.gate("--run", run_id)
        self.assertEqual(run.returncode, 1)
        self.assertIn("stale", run.stdout)

    def test_spec_size_alpha_format(self):
        self.init()
        path = self.project / "card.png"
        Image.new("RGB", (100, 140), "white").save(path)
        self.ok("approve", "deliverable", "--name", "poster", "--file", path, "--width", 100, "--height", 140,
                "--alpha", "required", "--format", "PNG")
        run = self.gate()
        self.assertEqual(run.returncode, 1)
        self.assertIn("alpha", run.stdout)
        img = Image.new("RGBA", (100, 140), (0, 0, 0, 0))
        ImageDraw.Draw(img).rectangle((10, 10, 90, 130), fill=(255, 255, 255, 255))
        img.save(path)
        self.ok("approve", "deliverable", "--name", "poster", "--file", path)
        self.assertEqual(self.gate().returncode, 0, self.gate().stdout)
        jpg = self.project / "card.jpg"
        Image.new("RGB", (100, 140), "white").save(jpg)
        self.ok("approve", "deliverable", "--name", "poster", "--file", jpg)
        run = self.gate()
        self.assertEqual(run.returncode, 1)
        self.assertIn("format", run.stdout)


class ZipTests(StudioBase):
    def make_zip(self, entries):
        path = self.project / "pack.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in entries:
                archive.writestr(name, data)
        return path

    @staticmethod
    def png(size, dot=False):
        buffer = io.BytesIO()
        img = Image.new("RGB", size, "white")
        if dot:
            ImageDraw.Draw(img).rectangle((2, 2, 17, 17), fill=(0, 0, 0))
        img.save(buffer, "PNG")
        return buffer.getvalue()

    def approve_zip(self, path):
        self.ok("approve", "deliverable", "--name", "poster", "--file", path, "--width", 64, "--height", 96,
                "--alpha", "any", "--format", "ZIP")

    def test_defect_on_multi_image_zip_is_refused(self):
        self.init()
        self.approve_zip(self.make_zip([("a.png", self.png((64, 96))), ("b.png", self.png((64, 96)))]))
        run = self.run_cli("defect", "add", "--deliverable", "poster", "--bbox", "0,0,40,40", "--kind", "seam", "--note", "x")
        self.assertEqual(run.returncode, 2, run.stdout)
        self.assertIn("own deliverable", run.stderr + run.stdout)

    def test_good_zip_passes(self):
        self.init()
        self.approve_zip(self.make_zip([("a.png", self.png((64, 96))), ("b.png", self.png((64, 96)))]))
        run = self.gate()
        self.assertEqual(run.returncode, 0, run.stdout)





class BriefTests(StudioBase):
    def test_bounded_but_never_drops_open_defects(self):
        self.init()
        self.approve_poster(self.poster())
        for i in range(30):
            self.defect([1, 1, 20 + i, 20 + i], note=f"open defect {i}")
        for i in range(10):
            self.defect([1, 1, 20, 20], note=f"old defect {i}")
            self.ok("defect", "close", "--id", f"D{31 + i}", "--status", "resolved", "--note", "fixed")
        out = self.ok("brief", "--max-lines", 20).stdout
        for i in range(1, 31):
            self.assertRegex(out, rf"\bD{i}\b")
        self.assertIn("omitted", out)
        small = self.ok("brief", "--max-lines", 40)
        self.assertLessEqual(len(self.ok("brief", "--max-lines", 60).stdout.splitlines()), 60)
        self.assertTrue(small.stdout)

    def test_brief_lists_store_contents_and_precedence(self):
        self.init()
        self.approve_poster(self.poster())
        self.defect(list(CARD), note="remove the dragon card")
        out = self.ok("brief").stdout
        for text in ("acme", "poster", "D1", "remove the dragon card", "Precedence"):
            self.assertIn(text, out)



class PreferenceTests(StudioBase):
    def test_brief_shows_confirmed_and_counts_proposed(self):
        self.init()
        self.ok("pref", "add", "--brand", "acme", "--rule", "Logo only from master file", "--check",
                "compare to master", "--confirmed")
        self.ok("pref", "add", "--brand", "acme", "--rule", "Prefer 2D, not 3D", "--check", "no bevels")
        self.ok("pref", "add", "--rule", "English filenames", "--check", "ascii names", "--confirmed")
        self.ok("pref", "add", "--brand", "other", "--rule", "Other brand rule", "--check", "x", "--confirmed")
        text = (self.home / "brands/acme/preferences.md").read_text()
        self.assertIn("- [confirmed] Logo only from master file — check: compare to master", text)
        out = self.ok("brief").stdout
        self.assertIn("Logo only from master file", out)
        self.assertIn("English filenames", out)
        self.assertNotIn("Prefer 2D", out)
        self.assertNotIn("Other brand rule", out)
        self.assertIn("1 proposed", out)

    def test_confirming_a_proposed_rule_replaces_it(self):
        self.ok("pref", "add", "--rule", "Minimal", "--check", "count elements")
        self.ok("pref", "add", "--rule", "Minimal", "--check", "count elements", "--confirmed")
        text = (self.home / "preferences.md").read_text()
        self.assertNotIn("[proposed] Minimal", text)
        self.assertIn("[confirmed] Minimal", text)

    def test_over_cap_exits_2(self):
        for i in range(12):
            run = self.run_cli("pref", "add", "--rule", f"Rule number {i} " + "x" * 100, "--check", "look")
            if run.returncode == 2:
                self.assertIn("consolidate", run.stderr)
                break
        else:
            self.fail("cap never reached")
        self.assertLessEqual(len((self.home / "preferences.md").read_text()), 1500)

    def test_unwritable_home_exits_2(self):
        blocker = Path(self.tmp.name) / "file"
        blocker.write_text("x")
        run = self.run_cli("pref", "add", "--rule", "r", "--check", "c", home=blocker / "sub")
        self.assertEqual(run.returncode, 2)
        self.assertIn("preferences", run.stderr)


class HookTests(StudioBase):
    def stop(self, payload, cwd=None):
        data = payload if isinstance(payload, str) else json.dumps(payload)
        run = self.run_cli("hook", "stop", stdin=data, cwd=cwd)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(run.stderr, "")
        return run.stdout

    def ready_store(self):
        self.init()
        self.approve_poster(self.poster())

    def test_completion_claim_without_gate_blocks_once(self):
        self.ready_store()
        payload = {"session_id": "s1", "cwd": str(self.project), "stop_hook_active": False,
                   "last_assistant_message": "All done, I verified the poster."}
        out = json.loads(self.stop(payload))
        self.assertEqual(out["decision"], "block")
        self.assertIn("gate", out["reason"])
        self.assertEqual(self.stop(payload), "")  # marker fallback: never twice for the same turn

    def test_stop_hook_active_never_blocks(self):
        self.ready_store()
        self.assertEqual(self.stop({"session_id": "s2", "cwd": str(self.project), "stop_hook_active": True,
                                    "last_assistant_message": "Done."}), "")

    def test_only_a_report_or_a_question_passes_without_a_gate(self):
        self.ready_store()
        for i, text in enumerate(("Should I remove both pillars or only one?",
                                  "Checked:\n- spec\nNot checked:\n- D1\nStill failing:\n- poster\n- D1 card still there",
                                  "Blocked: the master logo file is missing, so it is not done.",
                                  "Mình chưa xong phần logo, cần file gốc.")):
            self.assertEqual(self.stop({"session_id": f"q{i}", "cwd": str(self.project),
                                        "last_assistant_message": text}), "", text)

    def test_vietnamese_claim_blocks(self):
        self.ready_store()
        self.assertIn("block", self.stop({"session_id": "vn", "cwd": str(self.project),
                                          "last_assistant_message": "Đã hoàn thành và đã kiểm tra logo."}))

    def test_passing_gate_is_not_blocked(self):
        self.ready_store()
        self.assertEqual(self.gate().returncode, 0)
        self.assertEqual(self.stop({"session_id": "s3", "cwd": str(self.project),
                                    "last_assistant_message": "Done and verified."}), "")

    def test_claim_read_from_transcript(self):
        self.ready_store()
        transcript = Path(self.tmp.name) / "t.jsonl"
        lines = [{"type": "user", "message": {"role": "user", "content": "fix it"}},
                 {"type": "assistant", "message": {"role": "assistant",
                                                   "content": [{"type": "text", "text": "Final poster is done."}]}}]
        transcript.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
        out = self.stop({"session_id": "t", "cwd": str(self.project), "transcript_path": str(transcript)})
        self.assertIn("block", out)

    def test_no_store_and_malformed_input_are_silent(self):
        self.assertEqual(self.stop({"session_id": "n", "cwd": str(self.project),
                                    "last_assistant_message": "Done."}), "")
        self.ready_store()
        for data in ("not json", "[]", "", '{"cwd": 5}', '{"last_assistant_message": ["x"]}'):
            self.assertEqual(self.stop(data), "", data)
        run = self.run_cli("hook", "bogus", stdin="{}")
        self.assertEqual((run.returncode, run.stdout, run.stderr), (0, "", ""))

    def test_session_start_prints_brief_only_with_store(self):
        payload = json.dumps({"cwd": str(self.project), "source": "startup"})
        run = self.run_cli("hook", "session-start", stdin=payload)
        self.assertEqual((run.returncode, run.stdout), (0, ""))
        self.ready_store()
        run = self.run_cli("hook", "session-start", stdin=payload, cwd=Path(self.tmp.name))
        self.assertEqual(run.returncode, 0)
        self.assertIn("acme", run.stdout)
        (self.store / "state.json").write_text("garbage")
        run = self.run_cli("hook", "session-start", stdin=payload)
        self.assertEqual((run.returncode, run.stderr), (0, ""))
        self.assertEqual(len(run.stdout.strip().splitlines()), 1)
        self.assertTrue(run.stdout.startswith("image-studio: project store is corrupt: "), run.stdout)




class ResolvedProofTests(StudioBase):
    def setUp(self):
        super().setUp()
        self.init()
        self.approve_poster(self.poster(dots=True))
        self.defect(list(CARD), note="remove the dragon card")

    def verdict_all(self, run_id):
        self.ok("verdict", "--run", run_id, "--id", "D1", "--status", "pass", "--evidence", "card is gone at 200%")

    def test_defect_records_what_was_reported(self):
        defect = self.defects()[0]
        self.assertEqual(defect["reported_sha256"], self.state()["deliverables"]["poster"]["current_sha256"])
        self.assertRegex(defect["region_hash"], r"^[0-9a-f]{64}$")

    def test_resolved_without_any_change_fails(self):
        self.ok("defect", "close", "--id", "D1", "--status", "resolved", "--note", "removed the card")
        run_id = self.run_id(self.gate())
        self.verdict_all(run_id)
        run = self.gate("--run", run_id)
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertIn("D1 marked resolved but", run.stdout)

    def test_resolved_with_region_pixels_unchanged_fails(self):
        self.approve_poster(self.poster())  # only the dots changed; the card is still there
        self.ok("defect", "close", "--id", "D1", "--status", "resolved", "--note", "removed the card")
        run_id = self.run_id(self.gate())
        self.verdict_all(run_id)
        run = self.gate("--run", run_id)
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertIn("D1 marked resolved but its pixels are unchanged since it was reported", run.stdout)

    def test_real_fix_passes(self):
        self.approve_poster(self.poster(card=False))
        self.ok("defect", "close", "--id", "D1", "--status", "resolved", "--note", "removed the card")
        run_id = self.run_id(self.gate())
        self.verdict_all(run_id)
        self.assertEqual(self.gate("--run", run_id).returncode, 0)

    def test_defect_add_needs_the_approved_file(self):
        self.poster(card=False)  # edited after approval
        run = self.run_cli("defect", "add", "--deliverable", "poster", "--bbox", "1,1,9,9", "--kind", "scope",
                           "--note", "x")
        self.assertEqual(run.returncode, 2)
        self.assertIn("approve", run.stderr)

    def test_wontfix_needs_the_users_words(self):
        run = self.run_cli("defect", "close", "--id", "D1", "--status", "wontfix", "--note", "agent decided")
        self.assertEqual(run.returncode, 2)
        self.assertIn("--quote", run.stderr)
        self.ok("defect", "close", "--id", "D1", "--status", "wontfix", "--note", "user keeps it",
                "--quote", "keep the dragon card, it is part of the set")
        self.assertEqual(self.defects()[0]["history"][-1]["quote"], "keep the dragon card, it is part of the set")
        run = self.gate()
        self.assertEqual(run.returncode, 0, run.stdout)
        self.assertIn("D1 accepted by user (wontfix): keep the dragon card, it is part of the set", run.stdout)
        self.assertNotIn("remove the dragon card", run.stdout)


    def test_defect_that_disappears_fails_the_gate(self):
        self.approve_poster(self.poster(card=False))
        self.ok("defect", "close", "--id", "D1", "--status", "resolved", "--note", "removed the card")
        run_id = self.run_id(self.gate())
        self.verdict_all(run_id)
        self.assertEqual(self.gate("--run", run_id).returncode, 0)
        (self.store / "defects.jsonl").write_text("")
        run = self.gate()
        self.assertEqual(run.returncode, 1)
        self.assertIn("defect D1 disappeared from defects.jsonl", run.stdout)

    def test_edited_checklist_makes_the_run_stale(self):
        self.ok("defect", "close", "--id", "D1", "--status", "resolved", "--note", "removed the card")
        run_id = self.run_id(self.gate())
        self.verdict_all(run_id)
        path = self.poster(card=False)
        self.approve_poster(path)
        checklist_path = self.run_dir(run_id) / "checklist.json"
        checklist = json.loads(checklist_path.read_text())
        checklist["sha256"] = self.state()["deliverables"]["poster"]["current_sha256"]
        checklist["file"] = str(path)
        checklist_path.write_text(json.dumps(checklist))
        run = self.gate("--run", run_id)
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertIn("stale", run.stdout)

    def test_changing_the_spec_needs_a_quote(self):
        path = self.project / "poster.png"
        run = self.run_cli("approve", "deliverable", "--name", "poster", "--file", path, "--width", 100)
        self.assertEqual(run.returncode, 2)
        self.assertIn("--quote", run.stderr)
        self.ok("approve", "deliverable", "--name", "poster", "--file", path, "--alpha", "required",
                "--quote", "make it transparent")
        decision = self.state()["decisions"][-1]
        self.assertIn("alpha any", decision["text"])
        self.assertIn("→", decision["text"])
        self.assertIn("alpha required", decision["text"])
        self.ok("approve", "deliverable", "--name", "poster", "--file", path)  # same spec needs no quote

    def test_project_path_with_tilde(self):
        run = self.run_cli("brief", "--project", "~/project", cwd="/",
                           env_extra={"HOME": str(Path(self.tmp.name).resolve())})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("acme", run.stdout)

    def test_brief_truncates_long_notes_but_lists_every_open_defect(self):
        for i in range(3):
            self.defect([1, 1, 20, 20], note=f"long note {i} " + "x" * 400)
        out = self.ok("brief", "--max-lines", 5).stdout
        for defect_id in ("D1", "D2", "D3", "D4"):
            self.assertRegex(out, rf"\b{defect_id}\b")
        self.assertNotIn("x" * 130, out)
        self.assertIn("...", out)


class GateTrustTests(StudioBase):
    def stop(self, message, session="s", active=False):
        run = self.run_cli("hook", "stop", stdin=json.dumps({"session_id": session, "cwd": str(self.project),
                                                             "stop_hook_active": active,
                                                             "last_assistant_message": message}))
        self.assertEqual((run.returncode, run.stderr), (0, ""))
        return run.stdout

    def test_forged_gate_record_is_not_trusted(self):
        self.init()
        self.approve_poster(self.poster())
        self.defect(list(CARD), note="remove the card")
        self.ok("defect", "close", "--id", "D1", "--status", "wontfix", "--note", "x", "--quote", "keep")
        self.ok("defect", "add", "--deliverable", "poster", "--bbox", "1,1,20,20", "--kind", "scope", "--note", "y")
        current = self.state()["deliverables"]["poster"]["current_sha256"]
        real_run = self.run_id(self.gate())  # fails: D2 open, no verdicts
        for run_id in ("fake-run", real_run):
            state = self.state()
            state["gates"] = {"poster": {"deliverable": "poster", "sha256": current, "run_id": run_id}}
            (self.store / "state.json").write_text(json.dumps(state))
            self.assertIn("block", self.stop("Done.", session=run_id), run_id)
            self.assertIn("gate not passed", self.ok("brief").stdout)

    def test_marker_is_per_message(self):
        self.init()
        self.approve_poster(self.poster(card=False))
        self.defect(list(CARD), note="card on table")
        self.assertIn("block", self.stop("Done."))
        self.assertEqual(self.stop("Done."), "")  # same message again in the same turn
        self.assertEqual(self.stop("Done again, all fixed.", active=True), "")
        self.assertIn("block", self.stop("Done again, all fixed."))  # a later turn with a new claim



class FinalMessageTests(unittest.TestCase):
    BLOCK = [
        "Done. The logo is fixed.",
        "Đã xong, logo đã sửa.",
        "Hoàn thành.",
        "Xong rồi, không còn lỗi nào.",
        "All defects resolved, D3 no longer fails",
        "Here is the final file, ready to deliver.",
        "Đã kiểm tra logo xong.",
        "Done.",
        "All good, ready to deliver.",
        "Đã sửa xong D4",
        "Đã fix rồi",
        "Ổn rồi.",
        "Giao ảnh.",
        "finished the work",
        "completely resolved",
    ]
    ALLOW = [
        "Đang chạy gate cho poster.",
        "Here is v7 for review.",
        "Chưa xong, còn D4.",
        "not done yet",
        "chưa hoàn thành",
        "chưa fix",
        "Checked:\n- spec\nNot checked:\n- D2\nStill failing:\n- D1 card",
        "## Checked\n- logo\n## Not checked\n- none\n## Still failing\n- D3",
        "**Checked:** spec\n**Not checked:** D2\n**Still failing:** none",
        "Đã kiểm:\n- logo\nChưa kiểm:\n- góc\nCòn lỗi:\n- D2",
        "Should I remove both pillars or only one?",
        "Bạn muốn xuất thêm size khác không？",
        "Should I fix D1 now?",
        "Bạn Đạt ơi, fix D1 không?",
    ]

    CLAIM_THEN_QUESTION = (
        "Done. Anything else?",
        "Hoàn thành! Bạn muốn gì tiếp?",
        "All good, shipped. Anything else?",
        "Fixed the hat and it is ready. Want a JPEG too?",
    )
    EMPTY_REPORT = (
        "All done!\nChecked: spec\nNot checked: none\nStill failing: none",
        "Xong rồi.\nĐã kiểm: logo\nChưa kiểm: không\nCòn lỗi: không có",
    )

    def test_a_question_after_a_claim_does_not_hide_it(self):
        module = load_module()
        for text in self.CLAIM_THEN_QUESTION:
            self.assertTrue(module.claims_completion(text), text)
        self.assertFalse(module.claims_completion("Is the poster done?"))

    def test_only_a_report_that_admits_open_work_excuses_a_claim(self):
        module = load_module()
        for text in self.EMPTY_REPORT:
            self.assertFalse(module.admits_unfinished(text), text)
        self.assertTrue(module.admits_unfinished("Done with D3.\nChecked:\n- D3\nNot checked:\n- none\nStill failing:\n- D4 soft background"))

    def test_claims_completion(self):
        module = load_module()
        for text in self.BLOCK:
            self.assertTrue(module.claims_completion(text), text)
        for text in self.ALLOW[:6]:
            self.assertFalse(module.claims_completion(text), text)

    def test_questions_and_honest_reports_pass(self):
        module = load_module()
        for text in self.ALLOW[6:]:
            self.assertTrue(not module.claims_completion(text) or module.admits_unfinished(text), text)


class Round3HookTests(StudioBase):
    def stop(self, message, session="s", active=False, turn=None):
        payload = {"session_id": session, "cwd": str(self.project),
                   "stop_hook_active": active,
                   "last_assistant_message": message}
        if turn is not None:
            payload["turn_id"] = turn
        run = self.run_cli("hook", "stop", stdin=json.dumps(payload))
        self.assertEqual((run.returncode, run.stderr), (0, ""))
        return run.stdout

    def test_gate_valid_for_every_deliverable_never_blocks(self):
        self.init()
        self.approve_poster(self.poster())
        self.assertEqual(self.gate().returncode, 0)
        self.assertEqual(self.stop("Done."), "")

    def test_same_message_different_turn_id_blocks_again(self):
        self.init()
        self.approve_poster(self.poster())
        self.assertIn("block", self.stop("Done.", turn="t1"))
        self.assertEqual(self.stop("Done.", turn="t1"), "")
        self.assertIn("block", self.stop("Done.", turn="t2"))

    def test_same_message_blocks_again_after_the_store_changes(self):
        self.init()
        self.approve_poster(self.poster())
        self.assertIn("block", self.stop("Done."))
        self.assertEqual(self.stop("Done."), "")
        self.defect(list(CARD), note="remove the card")
        self.assertIn("block", self.stop("Done."))
        self.assertEqual(self.stop("Done.", active=True), "")

    def test_read_only_store_still_blocks(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root ignores folder permissions")
        self.init()
        self.approve_poster(self.poster())
        os.chmod(self.store, 0o555)
        try:
            self.assertIn("block", self.stop("Done."))
            self.assertIn("block", self.stop("Done."))
            self.assertEqual(self.stop("Done.", active=True), "")
        finally:
            os.chmod(self.store, 0o755)

    def test_corrupt_store_blocks_once_with_the_reason(self):
        self.init()
        self.approve_poster(self.poster())
        (self.store / "defects.jsonl").write_text("{broken\n")
        out = json.loads(self.stop("Done."))
        self.assertIn("project store is corrupt", out["reason"])
        self.assertEqual(self.stop("Done."), "")
        run = self.run_cli("hook", "session-start", stdin=json.dumps({"cwd": str(self.project)}))
        self.assertTrue(run.stdout.startswith("image-studio: project store is corrupt: "), run.stdout)


class Round3StoreTests(StudioBase):
    def setUp(self):
        super().setUp()
        self.init()

    def test_init_refuses_a_store_inside_another_store(self):
        sub = self.project / "client" / "job"
        sub.mkdir(parents=True)
        run = self.run_cli("init", "--project", sub, "--brand", "acme")
        self.assertEqual(run.returncode, 2)
        self.assertIn(str(self.store), run.stderr)

    def test_trivial_change_does_not_resolve_a_defect(self):
        self.approve_poster(self.poster())
        self.defect(list(CARD), note="remove the card")
        img = Image.open(self.project / "poster.png").convert("RGB")
        img.putpixel((CARD[0] + 5, CARD[1] + 5), (0, 0, 0))
        img.save(self.project / "poster.png")
        self.approve_poster(self.project / "poster.png")
        self.ok("defect", "close", "--id", "D1", "--status", "resolved", "--note", "removed")
        run = self.gate()
        self.assertEqual(run.returncode, 1)
        self.assertIn("D1 marked resolved but almost nothing changed in its box", run.stdout)
        self.assertTrue((self.store / "defects" / "D1-reported.png").is_file())

    def test_tiny_box_needs_a_quote(self):
        self.approve_poster(self.poster())
        run = self.run_cli("defect", "add", "--deliverable", "poster", "--bbox", "1,1,11,11", "--kind", "scope",
                           "--note", "dot")
        self.assertEqual(run.returncode, 2)
        self.assertIn("--quote", run.stderr)
        self.ok("defect", "add", "--deliverable", "poster", "--bbox", "1,1,11,11", "--kind", "scope", "--note", "dot",
                "--quote", "remove that tiny dot")
        self.assertEqual(self.defects()[0]["quote"], "remove that tiny dot")

    def test_id_gap_warns_in_brief_and_fails_the_gate(self):
        self.approve_poster(self.poster())
        for _ in range(3):
            self.defect([1, 1, 20, 20])
        lines = (self.store / "defects.jsonl").read_text().splitlines()
        (self.store / "defects.jsonl").write_text(lines[0] + "\n" + lines[2] + "\n")
        self.assertIn("WARNING: D2 missing from defects.jsonl", self.ok("brief").stdout)
        run = self.gate()
        self.assertEqual(run.returncode, 1)
        self.assertIn("D2 missing from defects.jsonl", run.stdout)


class Round4Tests(StudioBase):
    def test_hook_store_discovery_via_pointer_and_tmp_cwd(self):
        self.init()
        self.approve_poster(self.poster())
        # 1. hook stop with cwd=/tmp, no pointer, no env var: must allow
        pl = {"session_id": "sess_tmp", "cwd": "/tmp", "last_assistant_message": "Done."}
        run = self.run_cli("hook", "stop", stdin=json.dumps(pl))
        self.assertEqual(run.stdout, "")

        # 2. session-start with cwd=project, same session_id: writes pointer
        pl_start = {"session_id": "sess_tmp", "cwd": str(self.project)}
        run_start = self.run_cli("hook", "session-start", stdin=json.dumps(pl_start))
        self.assertEqual(run_start.returncode, 0)

        # 3. hook stop with cwd=/tmp, same session_id: must block
        run_stop = self.run_cli("hook", "stop", stdin=json.dumps(pl))
        self.assertIn("block", run_stop.stdout)

    def test_hook_store_discovery_via_claude_project_dir(self):
        self.init()
        self.approve_poster(self.poster())
        pl = {"session_id": "sess_env", "cwd": "/tmp", "last_assistant_message": "Done."}
        run = self.run_cli("hook", "stop", stdin=json.dumps(pl), env_extra={"CLAUDE_PROJECT_DIR": str(self.project)})
        self.assertIn("block", run.stdout)

    def test_pointer_pruning_older_than_7_days(self):
        self.init()
        sessions_dir = self.home / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        old_ptr = sessions_dir / "old_sess.json"
        old_ptr.write_text(json.dumps({"store": str(self.store)}))
        old_time = time.time() - 8 * 86400
        os.utime(old_ptr, (old_time, old_time))
        self.assertTrue(old_ptr.is_file())

        pl_start = {"session_id": "new_sess", "cwd": str(self.project)}
        self.run_cli("hook", "session-start", stdin=json.dumps(pl_start))
        self.assertFalse(old_ptr.is_file())
        self.assertTrue((sessions_dir / "new_sess.json").is_file())

    def test_gate_pass_self_verified_label(self):
        self.init()
        self.approve_poster(self.poster())
        self.defect(list(CARD), note="card on table")
        img = Image.open(self.project / "poster.png").convert("RGB")
        for x in range(CARD[0], CARD[2]):
            for y in range(CARD[1], CARD[3]):
                img.putpixel((x, y), (200, 200, 200))
        img.save(self.project / "poster.png")
        self.approve_poster(self.project / "poster.png")
        self.ok("defect", "close", "--id", "D1", "--status", "resolved", "--note", "fixed")
        run1 = self.gate()
        import re
        m = re.search(r"Run:\s+(\S+)", run1.stdout)
        run_id = m.group(1)
        self.ok("verdict", "--run", run_id, "--id", "D1", "--status", "pass",
                "--evidence", "looks completely fixed checked 100 crop", "--reviewer", "self")
        run2 = self.gate("--run", run_id)
        self.assertEqual(run2.returncode, 0)
        self.assertIn("Result: PASS (self-verified — not independently reviewed)", run2.stdout)
        state = json.loads((self.store / "state.json").read_text(encoding="utf-8"))
        self.assertTrue(state.get("gates", {}).get("poster", {}).get("self_verified"))
        brief = self.ok("brief").stdout
        self.assertIn("gate passed (self-verified)", brief)

    def test_gate_pass_independent_reviewer_no_self_verified_label(self):
        self.init()
        self.approve_poster(self.poster())
        self.defect(list(CARD), note="card on table")
        img = Image.open(self.project / "poster.png").convert("RGB")
        for x in range(CARD[0], CARD[2]):
            for y in range(CARD[1], CARD[3]):
                img.putpixel((x, y), (200, 200, 200))
        img.save(self.project / "poster.png")
        self.approve_poster(self.project / "poster.png")
        self.ok("defect", "close", "--id", "D1", "--status", "resolved", "--note", "fixed")
        run1 = self.gate()
        import re
        m = re.search(r"Run:\s+(\S+)", run1.stdout)
        run_id = m.group(1)
        self.ok("verdict", "--run", run_id, "--id", "D1", "--status", "pass",
                "--evidence", "looks completely fixed checked 100 crop", "--reviewer", "independent")
        run2 = self.gate("--run", run_id)
        self.assertEqual(run2.returncode, 0)
        self.assertIn("Result: PASS", run2.stdout)
        self.assertNotIn("self-verified", run2.stdout)
        state = json.loads((self.store / "state.json").read_text(encoding="utf-8"))
        self.assertFalse(state.get("gates", {}).get("poster", {}).get("self_verified", False))
        brief = self.ok("brief").stdout
        self.assertIn(f"gate passed run {run_id}", brief)
        self.assertNotIn("self-verified", brief)

    def test_gate_pass_survives_ascii_stdout_and_records_gate(self):
        self.init()
        self.approve_poster(self.poster())
        self.defect(list(CARD), note="card on table")
        img = Image.open(self.project / "poster.png").convert("RGB")
        for x in range(CARD[0], CARD[2]):
            for y in range(CARD[1], CARD[3]):
                img.putpixel((x, y), (200, 200, 200))
        img.save(self.project / "poster.png")
        self.approve_poster(self.project / "poster.png")
        self.ok("defect", "close", "--id", "D1", "--status", "resolved", "--note", "fixed")
        run1 = self.gate()
        import re
        m = re.search(r"Run:\s+(\S+)", run1.stdout)
        run_id = m.group(1)
        self.ok("verdict", "--run", run_id, "--id", "D1", "--status", "pass",
                "--evidence", "looks completely fixed checked 100 crop", "--reviewer", "self")
        run2 = self.run_cli("gate", "--deliverable", "poster", "--run", run_id, env_extra={"PYTHONIOENCODING": "ascii"})
        self.assertEqual(run2.returncode, 0)
        self.assertNotIn("Traceback", run2.stderr)
        self.assertIn("Result: PASS (self-verified - not independently reviewed)", run2.stdout)
        state = json.loads((self.store / "state.json").read_text(encoding="utf-8"))
        self.assertTrue(state.get("gates", {}).get("poster", {}).get("self_verified"))

    def test_self_verified_single_source_of_truth_rewrite_verdicts_independent(self):
        self.init()
        self.approve_poster(self.poster())
        self.defect(list(CARD), note="card on table")
        img = Image.open(self.project / "poster.png").convert("RGB")
        for x in range(CARD[0], CARD[2]):
            for y in range(CARD[1], CARD[3]):
                img.putpixel((x, y), (200, 200, 200))
        img.save(self.project / "poster.png")
        self.approve_poster(self.project / "poster.png")
        self.ok("defect", "close", "--id", "D1", "--status", "resolved", "--note", "fixed")
        run1 = self.gate()
        import re
        m = re.search(r"Run:\s+(\S+)", run1.stdout)
        run_id = m.group(1)
        self.ok("verdict", "--run", run_id, "--id", "D1", "--status", "pass",
                "--evidence", "looks completely fixed checked 100 crop", "--reviewer", "self")
        run2 = self.gate("--run", run_id)
        self.assertEqual(run2.returncode, 0)
        self.assertIn("Result: PASS (self-verified — not independently reviewed)", run2.stdout)
        brief1 = self.ok("brief").stdout
        self.assertIn("gate passed (self-verified)", brief1)

        module = load_module()
        self.assertTrue(hasattr(module, "is_self_verified"))
        run_dir = self.store / "gate" / run_id
        self.assertTrue(module.is_self_verified(run_dir))

        self.ok("verdict", "--run", run_id, "--id", "D1", "--status", "pass",
                "--evidence", "looks completely fixed checked 100 crop", "--reviewer", "independent")
        run3 = self.gate("--run", run_id)
        self.assertEqual(run3.returncode, 0)
        self.assertIn("Result: PASS", run3.stdout)
        self.assertNotIn("self-verified", run3.stdout)
        brief2 = self.ok("brief").stdout
        self.assertNotIn("self-verified", brief2)
        self.assertIn(f"gate passed run {run_id}", brief2)
        self.assertFalse(module.is_self_verified(run_dir))

    def test_session_pointer_invalid_store_value_ignored_silently(self):
        self.init()
        self.approve_poster(self.poster())
        sessions_dir = self.home / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        ptr = sessions_dir / "sess_list.json"
        ptr.write_text(json.dumps({"store": ["x"]}))
        pl = {"session_id": "sess_list", "cwd": "/tmp", "last_assistant_message": "Done."}
        module = load_module()
        old_env = os.environ.get("IMAGE_STUDIO_HOME")
        try:
            os.environ["IMAGE_STUDIO_HOME"] = str(self.home)
            self.assertEqual(module.discover_hook_store(pl), (None, None))
        finally:
            if old_env is None:
                os.environ.pop("IMAGE_STUDIO_HOME", None)
            else:
                os.environ["IMAGE_STUDIO_HOME"] = old_env
        run = self.run_cli("hook", "stop", stdin=json.dumps(pl))
        self.assertEqual(run.returncode, 0)
        self.assertEqual(run.stdout, "")

    def test_session_pointer_null_byte_session_id_ignored_silently(self):
        self.init()
        pl = {"session_id": "a\x00b", "cwd": str(self.project)}
        run = self.run_cli("hook", "session-start", stdin=json.dumps(pl))
        self.assertEqual(run.returncode, 0)
        self.assertIn("image-studio project memory", run.stdout)
        sessions_dir = self.home / "sessions"
        if sessions_dir.is_dir():
            self.assertEqual(list(sessions_dir.glob("*.json")), [])

    def test_session_pointer_folder_not_named_image_studio_ignored(self):
        self.init()
        self.approve_poster(self.poster())
        other_dir = Path(self.tmp.name) / "not_store"
        other_dir.mkdir(parents=True, exist_ok=True)
        (other_dir / "state.json").write_text(json.dumps({"schema_version": 1}))
        sessions_dir = self.home / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        ptr = sessions_dir / "sess_other.json"
        ptr.write_text(json.dumps({"store": str(other_dir)}))
        pl = {"session_id": "sess_other", "cwd": "/tmp", "last_assistant_message": "Done."}
        run = self.run_cli("hook", "stop", stdin=json.dumps(pl))
        self.assertEqual(run.returncode, 0)
        self.assertEqual(run.stdout, "")


class SourceTests(unittest.TestCase):
    def test_python_3_9_syntax_and_no_getdata(self):
        source = SCRIPT.read_text(encoding="utf-8")
        ast.parse(source, feature_version=(3, 9))
        self.assertNotIn("getdata", source)
        self.assertNotIn("match ", [line.strip()[:6] for line in source.splitlines()])

    def test_help_documents_every_subcommand(self):
        run = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0)
        for name in ("init", "approve", "defect", "brief", "gate", "verdict", "pref", "hook"):
            self.assertIn(name, run.stdout)
        self.assertIn("pref add does not use the project store", run.stdout)
        self.assertIn("--quote", run.stdout)


class SliceBNewBehaviorTests(StudioBase):
    def stop(self, message, session="s", active=False, turn=None):
        payload = {"session_id": session, "cwd": str(self.project),
                   "stop_hook_active": active,
                   "last_assistant_message": message}
        if turn is not None:
            payload["turn_id"] = turn
        run = self.run_cli("hook", "stop", stdin=json.dumps(payload))
        self.assertEqual((run.returncode, run.stderr), (0, ""))
        return run.stdout

    def test_stop_hook_completion_claims_table(self):
        self.init()
        self.approve_poster(self.poster())
        must_block = [
            "Xong rồi.",
            "Done.",
            "All defects fixed, ready to deliver",
            "Đã sửa xong D4",
            "Xong rồi, không còn lỗi nào.",
            "The poster is ready.",
            "Here is the final file: out.png",
            "Good to go",
        ]
        for text in must_block:
            out = self.stop(text, session="blk")
            data = json.loads(out)
            self.assertEqual(data.get("decision"), "block", text)
            self.assertIn("plain words", data.get("reason", ""), text)
            self.assertIn("poster has not passed the final check", data.get("reason", ""), text)

        must_not_block = [
            "Đang chạy gate cho poster.",
            "Here is v7 for review.",
            "Chưa xong, còn D4.",
            "Checked:\n- spec\nNot checked:\n- none\nStill failing:\n- none",
            "Which version do you prefer?",
            "Can you check this?",
            "not done yet",
            "chưa hoàn thành",
            "chưa fix",
            "Đã sửa giao diện của poster.",
            "Giao diện poster đã chỉnh màu nền.",
            "The image is not completely fixed yet",
            "D2 has not been fixed",
            "It isn't done",
            "I haven't finished yet",
            "I fixed the horn edge; next I will check the logo.",
            "Resolved D2, still working on D3.",
            "Mình đã sửa xong D1, D2 vẫn còn lỗi",
        ]
        for text in must_not_block:
            out = self.stop(text, session="allow")
            self.assertEqual(out, "", text)

    def test_session_start_card_format_and_size_bound(self):
        self.init()
        self.approve_poster(self.poster())
        self.defect(list(CARD), note="dragon card to remove")
        self.ok("pref", "add", "--brand", "acme", "--rule", "No bevels", "--check", "edges", "--confirmed")
        payload = json.dumps({"cwd": str(self.project), "source": "startup"})
        run = self.run_cli("hook", "session-start", stdin=payload)
        self.assertEqual(run.returncode, 0)
        out = run.stdout
        self.assertLessEqual(len(out), 2400)
        self.assertIn("image-studio project memory", out)
        self.assertIn("D1", out)
        self.assertIn("poster", out)
        self.assertIn("No bevels", out)
        self.assertIn("Commands: run studio_state.py --help; do not read its source.", out)

    def test_session_start_card_size_bound_with_30_open_defects(self):
        self.init()
        self.approve_poster(self.poster())
        for i in range(30):
            self.defect([1, 1, 20, 20], note=f"defect number {i} " + "long description " * 10)
        for i in range(5):
            self.defect([1, 1, 20, 20], note=f"resolved defect {i}")
            self.ok("defect", "close", "--id", f"D{31 + i}", "--status", "resolved", "--note", "fixed")
        payload = json.dumps({"cwd": str(self.project), "source": "startup"})
        run = self.run_cli("hook", "session-start", stdin=payload)
        self.assertEqual(run.returncode, 0)
        out = run.stdout
        self.assertLessEqual(len(out), 2400)
        for i in range(1, 31):
            self.assertIn(f"D{i}", out)
        self.assertIn("5 resolved - regression-checked by the gate", out)
        self.assertIn("Commands: run studio_state.py --help; do not read its source.", out)

    def test_legacy_store_does_not_crash(self):
        self.init()
        poster_path = self.poster()
        module = load_module()
        digest = module.sha256_file(poster_path)
        state = {
            "schema_version": 1,
            "brand": "acme",
            "plugin_version_last_seen": "2.3.0",
            "deliverables": {
                "poster": {
                    "spec": {"width": 200, "height": 150, "format": "PNG", "alpha": "any"},
                    "current_sha256": digest,
                    "path": "poster.png",
                }
            },
            "masters": {
                "logo": {"path": "masters/logo.png", "sha256": "0" * 64, "role": "logo"}
            },
            "decisions": [{"time": "2026-10-18T00:00:00Z", "text": "approved master", "quote": ""}],
            "gates": {},
        }
        (self.store / "state.json").write_text(json.dumps(state))
        defects = [
            {
                "id": "D1",
                "deliverable": "poster",
                "bbox": [10, 10, 30, 30],
                "kind": "logo",
                "status": "open",
                "note": "legacy logo defect",
                "master": "logo",
                "master_sha256": "0" * 64,
                "member": "none.png",
                "source": "user",
            },
            {
                "id": "D2",
                "deliverable": "poster",
                "bbox": [40, 40, 60, 60],
                "kind": "seam",
                "status": "resolved",
                "note": "legacy defect missing crop and region hash",
                "source": "user",
            }
        ]
        (self.store / "defects.jsonl").write_text("\n".join(json.dumps(d) for d in defects) + "\n")
        b_run = self.run_cli("brief")
        self.assertEqual(b_run.returncode, 0, b_run.stderr)
        g_run = self.run_cli("gate", "--deliverable", "poster")
        self.assertEqual(g_run.returncode, 1, g_run.stdout + g_run.stderr)
        h_start = self.run_cli("hook", "session-start", stdin=json.dumps({"cwd": str(self.project)}))
        self.assertEqual(h_start.returncode, 0, h_start.stderr)
        self.assertIn("D1", h_start.stdout)
        h_stop = self.run_cli("hook", "stop", stdin=json.dumps({"cwd": str(self.project), "last_assistant_message": "Done."}))
        self.assertEqual(h_stop.returncode, 0, h_stop.stderr)
        self.assertIn('"decision": "block"', h_stop.stdout)

    def test_epilog_cheat_sheet_has_every_subcommand_with_example(self):
        run = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0)
        for cmd in ("init", "approve deliverable", "defect add", "defect close", "brief", "gate", "verdict", "pref add", "hook"):
            self.assertIn(cmd, run.stdout)
        self.init()
        brief_out = self.ok("brief").stdout
        self.assertIn("--help", brief_out)




class LiteScopeTests(StudioBase):
    def stop(self, message, cwd, session="s"):
        run = self.run_cli("hook", "stop", stdin=json.dumps({"session_id": session, "cwd": str(cwd),
                                                             "last_assistant_message": message}), cwd=cwd)
        self.assertEqual((run.returncode, run.stderr), (0, ""))
        return run.stdout

    def test_nested_git_repo_below_store_project_is_not_policed(self):
        self.init()
        self.approve_poster(self.poster())
        repo = self.project / "work" / "plugin-repo"
        (repo / ".git").mkdir(parents=True)
        (repo / "src").mkdir()
        self.assertEqual(self.stop("Done.", repo / "src"), "")
        start = self.run_cli("hook", "session-start", stdin=json.dumps({"session_id": "dev", "cwd": str(repo)}), cwd=repo)
        self.assertEqual(start.stdout, "")
        self.assertFalse((self.home / "sessions" / "dev.json").exists())

    def test_project_that_is_itself_a_git_repo_is_still_policed(self):
        (self.project / ".git").mkdir()
        self.init()
        self.approve_poster(self.poster())
        self.assertIn("block", self.stop("Done.", self.project))

    def test_block_reason_names_open_defects_in_plain_words(self):
        self.init()
        self.approve_poster(self.poster())
        did = self.defect(list(CARD), note="dragon card still visible")
        out = json.loads(self.stop("Xong rồi.", self.project))
        self.assertIn("dragon card still visible (%s)" % did, out["reason"])
        self.assertNotIn("Checked / Not checked / Still failing", out["reason"])


class PointerAndCardTests(StudioBase):
    def stop(self, message, cwd, session):
        run = self.run_cli("hook", "stop", stdin=json.dumps({"session_id": session, "cwd": str(cwd),
                                                             "last_assistant_message": message}))
        self.assertEqual((run.returncode, run.stderr), (0, ""))
        return run.stdout

    def write_pointer(self, session, data):
        sessions = self.home / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / f"{session}.json").write_text(json.dumps(data))

    def test_legacy_pointer_without_cwd_is_ignored(self):
        self.init()
        self.approve_poster(self.poster())
        self.write_pointer("legacy", {"store": str(self.store), "time": "2026-10-17T18:30:21Z"})
        self.assertEqual(self.stop("Done.", "/tmp", "legacy"), "")

    def test_pointer_from_a_nested_dev_repo_is_ignored(self):
        self.init()
        self.approve_poster(self.poster())
        repo = self.project / "work" / "plugin-repo"
        (repo / ".git").mkdir(parents=True)
        self.write_pointer("dev", {"store": str(self.store), "cwd": str(repo)})
        self.assertEqual(self.stop("Done.", "/tmp", "dev"), "")

    def test_pointer_written_at_session_start_still_catches_cd_out(self):
        self.init()
        self.approve_poster(self.poster())
        self.run_cli("hook", "session-start", stdin=json.dumps({"session_id": "job", "cwd": str(self.project)}))
        data = json.loads((self.home / "sessions" / "job.json").read_text())
        self.assertEqual(Path(data["cwd"]).resolve(), self.project)
        self.assertIn("block", self.stop("Done.", "/tmp", "job"))

    def test_after_this_round_is_not_a_claim(self):
        self.init()
        self.approve_poster(self.poster())
        for i, text in enumerate(("Xong đợt này tôi gộp mục 1, 2, 4 vào một lần.",
                                  "Done with this step, starting the logo now")):
            self.assertEqual(self.stop(text, self.project, f"r{i}"), "", text)
        for i, text in enumerate(("Xong rồi.", "Done with the poster.", "Done with the logo and the poster is final.", "Xong việc.")):
            self.assertIn("block", self.stop(text, self.project, f"b{i}"), text)

    def test_card_has_a_hard_cap_and_keeps_every_open_id(self):
        self.init()
        self.approve_poster(self.poster())
        lines = [json.dumps({"id": f"D{i}", "deliverable": "poster", "bbox": [1, 1, 40, 40], "kind": "seam",
                             "status": "open", "note": "long note " * 10, "source": "user"}) for i in range(1, 301)]
        (self.store / "defects.jsonl").write_text("\n".join(lines) + "\n")
        out = self.run_cli("hook", "session-start", stdin=json.dumps({"cwd": str(self.project)})).stdout
        for i in (1, 150, 300):
            self.assertIn(f"D{i}", out)
        self.assertLessEqual(len(out.rstrip("\n")), 2400 + 300 * 6)  # IDs are never dropped
        few = 40
        (self.store / "defects.jsonl").write_text("\n".join(lines[:few]) + "\n")
        out = self.run_cli("hook", "session-start", stdin=json.dumps({"cwd": str(self.project)})).stdout
        self.assertLessEqual(len(out.rstrip("\n")), 2400)
        self.assertIn(f"D{few}", out)


class LessonTests(StudioBase):
    def passed_gate(self):
        self.init()
        self.approve_poster(self.poster())
        self.assertEqual(self.gate().returncode, 0)

    def lessons(self):
        path = self.home / "lessons.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.is_file() else []

    def test_lesson_needs_mistake_cause_and_check(self):
        self.init()
        run = self.run_cli("lesson", "add", "--mistake", "x", "--cause", " ", "--check", "y")
        self.assertEqual(run.returncode, 2)
        self.assertEqual(self.lessons(), [])

    def test_defect_after_delivery_needs_a_lesson_before_the_gate_passes(self):
        self.passed_gate()
        out = self.ok("defect", "add", "--deliverable", "poster", "--bbox", "10,10,60,60", "--kind", "artifact", "--note", "soft corner").stdout
        self.assertIn("lesson add --defect D1", out)
        self.assertTrue(self.defects()[0]["needs_lesson"])
        self.ok("defect", "close", "--id", "D1", "--status", "wontfix", "--note", "ok", "--quote", "leave it")
        run = self.gate()
        self.assertEqual(run.returncode, 1)
        self.assertIn("D1 was reported after delivery and has no lesson", run.stdout)
        self.ok("lesson", "add", "--defect", "D1", "--mistake", "missed a soft corner", "--cause", "only checked display size",
                "--check", "inspect corners at 100%")
        self.assertEqual(self.lessons()[0]["kind"], "artifact")
        self.assertEqual(self.gate().returncode, 0)

    def test_defect_before_delivery_needs_no_lesson(self):
        self.init()
        self.approve_poster(self.poster())
        self.defect([10, 10, 60, 60])
        self.assertNotIn("needs_lesson", self.defects()[0])

    def test_card_and_brief_show_relevant_lessons_capped(self):
        self.init()
        self.approve_poster(self.poster())
        for i in range(7):
            self.ok("lesson", "add", "--mistake", f"mistake {i}", "--cause", "c", "--check", f"check {i}", "--kind", "seam")
        self.ok("lesson", "add", "--mistake", "other brand", "--cause", "c", "--check", "x", "--brand", "zeta")
        card = self.run_cli("hook", "session-start", stdin=json.dumps({"cwd": str(self.project)})).stdout
        self.assertIn("Lessons from earlier jobs", card)
        self.assertEqual(card.count("-> check:"), 5)
        self.assertIn("mistake 6", card)
        self.assertNotIn("other brand", card)
        self.assertIn("Lessons from earlier jobs", self.ok("brief").stdout)

    def test_same_mistake_in_two_jobs_proposes_a_rule(self):
        self.init()
        out1 = self.ok("lesson", "add", "--mistake", "halo", "--cause", "c", "--check", "dark backdrop", "--kind", "seam").stdout
        self.assertNotIn("pref add", out1)
        other = Path(self.tmp.name) / "job2"
        other.mkdir()
        self.ok("init", "--project", other, "--brand", "acme")
        out2 = self.ok("lesson", "add", "--project", other, "--mistake", "halo again", "--cause", "c", "--check", "dark backdrop",
                       "--kind", "seam").stdout
        self.assertIn("has now happened in 2 jobs", out2)
        self.assertIn("pref add --brand acme", out2)
        self.assertIn("only after the user agrees", out2)

    def test_lesson_list_and_corrupt_lines_are_tolerated(self):
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "lessons.jsonl").write_text("not json\n" + json.dumps({"id": "L1", "mistake": "m", "check": "c"}) + "\n")
        out = self.ok("lesson", "list").stdout
        self.assertIn("L1", out)
        self.init()
        self.ok("lesson", "add", "--mistake", "m2", "--cause", "c2", "--check", "k2")
        self.assertIn("L2", self.ok("lesson", "list").stdout)


class LessonEdgeTests(StudioBase):
    def lessons(self):
        path = self.home / "lessons.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.is_file() else []

    def test_missing_lesson_makes_the_card_and_stop_hook_treat_the_gate_as_not_passed(self):
        self.init()
        self.approve_poster(self.poster())
        self.assertEqual(self.gate().returncode, 0)
        self.ok("defect", "add", "--deliverable", "poster", "--bbox", "10,10,60,60", "--kind", "seam", "--note", "seam")
        self.ok("defect", "close", "--id", "D1", "--status", "wontfix", "--note", "ok", "--quote", "leave it")
        card = self.run_cli("hook", "session-start", stdin=json.dumps({"cwd": str(self.project)})).stdout
        self.assertIn("gate not passed", card)
        stop = self.run_cli("hook", "stop", stdin=json.dumps({"cwd": str(self.project), "session_id": "s", "last_assistant_message": "Done."})).stdout
        self.assertIn("block", stop)

    def test_agent_sourced_defect_after_delivery_needs_no_lesson(self):
        self.init()
        self.approve_poster(self.poster())
        self.assertEqual(self.gate().returncode, 0)
        self.ok("defect", "add", "--deliverable", "poster", "--bbox", "10,10,60,60", "--kind", "seam", "--note", "x", "--source", "agent")
        self.assertNotIn("needs_lesson", self.defects()[0])

    def test_lesson_outside_a_store_and_bad_input(self):
        run = self.run_cli("lesson", "add", "--mistake", "m", "--cause", "c", "--check", "k", cwd=Path(self.tmp.name))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotIn("project", self.lessons()[0])
        run = self.run_cli("lesson", "add", "--defect", "D1", "--mistake", "m", "--cause", "c", "--check", "k", cwd=Path(self.tmp.name))
        self.assertEqual(run.returncode, 2)
        self.init()
        self.assertEqual(self.run_cli("lesson", "add", "--defect", "D9", "--mistake", "m", "--cause", "c", "--check", "k").returncode, 2)
        run = self.run_cli("lesson", "add", "--mistake", "mail a@b.co", "--cause", "c", "--check", "k")
        self.assertEqual(run.returncode, 2)
        self.assertEqual(len(self.lessons()), 1)

    def test_rule_proposal_once_and_never_for_other(self):
        self.init()
        other = Path(self.tmp.name) / "job2"; other.mkdir()
        self.ok("init", "--project", other, "--brand", "acme")
        third = Path(self.tmp.name) / "job3"; third.mkdir()
        self.ok("init", "--project", third, "--brand", "acme")
        add = lambda proj, kind: self.ok("lesson", "add", "--project", proj, "--mistake", "m", "--cause", "c", "--check", "dark backdrop", "--kind", kind).stdout
        self.assertNotIn("pref add", add(self.project, "other"))
        self.assertNotIn("pref add", add(other, "other"))
        add(self.project, "seam")
        self.assertIn("pref add --brand acme", add(other, "seam"))
        self.assertNotIn("pref add", add(third, "seam"))

    def test_parallel_lesson_adds_keep_every_line(self):
        self.init()
        env = dict(os.environ, IMAGE_STUDIO_HOME=str(self.home))
        procs = [subprocess.Popen([sys.executable, str(SCRIPT), "lesson", "add", "--mistake", f"m{i}", "--cause", "c", "--check", "k"],
                                  cwd=str(self.project), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for i in range(8)]
        for proc in procs: self.assertEqual(proc.wait(), 0)
        lessons = self.lessons()
        self.assertEqual(len(lessons), 8)
        self.assertEqual(len({l["id"] for l in lessons}), 8)


class TasteTests(StudioBase):
    def card(self):
        return self.run_cli("hook", "session-start", stdin=json.dumps({"cwd": str(self.project)})).stdout

    def test_taste_is_recorded_per_brand_and_shown_newest_first(self):
        self.init()
        self.approve_poster(self.poster())
        for i in range(8):
            self.ok("taste", "add", "--aspect", "color", "--note", f"liked palette {i}", "--quote", "đẹp", "--deliverable", "poster")
        self.ok("taste", "add", "--brand", "zeta", "--note", "other brand taste")
        path = self.home / "brands" / "acme" / "taste.jsonl"
        items = [json.loads(l) for l in path.read_text().splitlines()]
        self.assertEqual(items[0]["deliverable"], "poster")
        card = self.card()
        self.assertIn("Your taste (match it):", card)
        self.assertIn("liked palette 7", card)
        self.assertNotIn("liked palette 1", card)
        self.assertNotIn("other brand taste", card)
        self.assertIn("taste add", card)
        self.assertLessEqual(len(card.rstrip("\n")), 2400)
        self.assertIn("Your taste", self.ok("brief").stdout)
        self.assertIn("other brand taste", self.ok("taste", "list", "--brand", "zeta").stdout)

    def test_general_taste_without_a_store_and_bad_input(self):
        run = self.run_cli("taste", "add", "--note", "clean flat icons", "--aspect", "style", cwd=Path(self.tmp.name))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue((self.home / "taste.jsonl").is_file())
        self.assertEqual(self.run_cli("taste", "add", "--note", " ").returncode, 2)
        self.assertEqual(self.run_cli("taste", "add", "--note", "x", "--aspect", "smell").returncode, 2)
        self.assertEqual(self.run_cli("taste", "add", "--note", "write a@b.co").returncode, 2)

    def test_lesson_records_what_worked(self):
        self.init()
        self.approve_poster(self.poster())
        self.ok("lesson", "add", "--mistake", "regenerated the whole hat twice", "--cause", "prompt too broad",
                "--check", "crop to the brim", "--worked", "masked brim-only patch", "--kind", "artifact")
        self.assertIn("worked: masked brim-only patch", self.card())


class TasteOrderTests(StudioBase):
    def test_brand_and_general_notes_are_merged_newest_first_and_deduplicated(self):
        self.init()
        self.approve_poster(self.poster())
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "brands" / "acme").mkdir(parents=True)
        gen = [{"note": f"general {i}", "time": f"2026-10-0{i}T00:00:00Z"} for i in range(1, 5)]
        brand = [{"note": f"brand {i}", "time": f"2026-10-1{i}T00:00:00Z"} for i in range(1, 6)]
        brand.append({"note": "Brand 5", "time": "2026-10-19T00:00:00Z"})
        (self.home / "taste.jsonl").write_text("".join(json.dumps(x) + "\n" for x in gen))
        (self.home / "brands" / "acme" / "taste.jsonl").write_text("".join(json.dumps(x) + "\n" for x in brand))
        card = self.run_cli("hook", "session-start", stdin=json.dumps({"cwd": str(self.project)})).stdout
        shown = [l for l in card.splitlines() if l.startswith("- [other]")]
        self.assertEqual(len(shown), 6)
        self.assertIn("Brand 5", shown[0])
        self.assertEqual(sum("rand 5" in l for l in shown), 1)
        self.assertIn("general 4", "\n".join(shown))
        self.assertNotIn("general 1", card)

    def test_reminder_survives_the_hard_cap(self):
        self.init()
        self.approve_poster(self.poster())
        lines = [json.dumps({"id": f"D{i}", "deliverable": "poster", "bbox": [1, 1, 40, 40], "kind": "seam", "status": "open",
                             "note": "long " * 30, "source": "user"}) for i in range(1, 121)]
        (self.store / "defects.jsonl").write_text("\n".join(lines) + "\n")
        card = self.run_cli("hook", "session-start", stdin=json.dumps({"cwd": str(self.project)})).stdout
        self.assertIn("taste add", card)
        self.assertIn("D120", card)


class BrandKitTests(StudioBase):
    def test_set_show_and_card_summary(self):
        self.init()
        self.approve_poster(self.poster())
        logo = self.poster("logo.png")
        ref = self.poster("style.png")
        out = self.ok("brand", "set", "--brand", "acme", "--color", "gold=#e1c178:accent", "--color", "navy=#0B152C:background",
                      "--font", "title=Cinzel", "--logo", logo, "--ref", f"{ref}=style", "--dont", "no 3D render look").stdout
        self.assertIn("gold #E1C178 (accent)", out)
        kit = json.loads((self.home / "brands" / "acme" / "brand.json").read_text())
        self.assertEqual(len(kit["refs"]), 1)
        card = self.run_cli("hook", "session-start", stdin=json.dumps({"cwd": str(self.project)})).stdout
        self.assertIn("Brand kit: palette #E1C178 #0B152C", card)
        self.assertIn("1 approved refs", card)
        shown = self.ok("brand", "show").stdout
        self.assertIn("never redraw", shown)
        self.assertIn("[style]", shown)

    def test_changed_reference_is_flagged_and_bad_input_is_refused(self):
        self.init()
        ref = self.poster("style.png")
        self.ok("brand", "set", "--brand", "acme", "--ref", f"{ref}=style")
        Image.new("RGB", (10, 10), "red").save(ref)
        self.assertIn("MISSING OR CHANGED", self.ok("brand", "show", "--brand", "acme").stdout)
        for bad in (["--color", "gold=E1C178"], ["--color", "gold"], ["--ref", "/nope.png=style"], ["--remove", "colors:none"],
                    ["--do", "mail a@b.co"]):
            self.assertEqual(self.run_cli("brand", "set", "--brand", "acme", *bad).returncode, 2, bad)

    def test_wrong_shape_brand_file_is_tolerated(self):
        self.init()
        (self.home / "brands" / "acme").mkdir(parents=True)
        (self.home / "brands" / "acme" / "brand.json").write_text(json.dumps({"colors": [1, 2], "fonts": {"title": 3}, "do": "x", "logo": 5}))
        self.ok("brief")
        self.ok("brand", "show", "--brand", "acme")
        self.ok("brand", "set", "--brand", "acme", "--color", "gold=#E1C178")
        self.assertIn("image-studio project memory", self.run_cli("hook", "session-start", stdin=json.dumps({"cwd": str(self.project)})).stdout)

    def test_remove_entries(self):
        self.init()
        self.ok("brand", "set", "--brand", "acme", "--color", "gold=#E1C178", "--dont", "no bevels")
        self.ok("brand", "set", "--brand", "acme", "--remove", "colors:gold", "--remove", "dont:no bevels")
        kit = json.loads((self.home / "brands" / "acme" / "brand.json").read_text())
        self.assertNotIn("colors", kit)
        self.assertNotIn("dont", kit)


class CarryOverTests(StudioBase):
    """A resolved defect whose pixels did not change keeps its earlier pass; only changed regions need a new verdict."""

    def two_fixed_defects(self):
        self.init()
        self.approve_poster(self.poster(card=True, dots=True))
        d1 = self.defect(list(DOTS[0]))
        d2 = self.defect(list(CARD))
        self.approve_poster(self.poster(card=False, dots=False))
        for did in (d1, d2):
            self.ok("defect", "close", "--id", did, "--status", "resolved", "--note", "removed")
        run = self.run_id(self.gate())
        for did in (d1, d2):
            self.ok("verdict", "--run", run, "--id", did, "--status", "pass", "--evidence", "region is clean at 100%")
        self.assertEqual(self.gate("--run", run).returncode, 0)
        return d1, d2

    def test_unchanged_regions_carry_their_pass(self):
        d1, d2 = self.two_fixed_defects()
        first = self.gate()
        self.assertIn("Carried 2 verdict(s)", first.stdout)
        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertIn("unchanged since run", first.stdout)

    def test_a_changed_region_needs_a_new_verdict(self):
        d1, d2 = self.two_fixed_defects()
        img = Image.open(self.project / "poster.png").convert("RGB")
        ImageDraw.Draw(img).rectangle((125, 45, 140, 60), fill=(0, 0, 255))
        img.save(self.project / "poster.png")
        self.approve_poster(self.project / "poster.png")
        run = self.gate()
        self.assertIn("Carried 1 verdict(s)", run.stdout)
        self.assertEqual(run.returncode, 1)
        self.assertIn(f"{d2}: no verdict yet", run.stdout)
        self.assertNotIn(f"{d1}: no verdict yet", run.stdout)

    def test_a_forged_earlier_verdict_is_not_carried(self):
        d1, d2 = self.two_fixed_defects()
        for vfile in (self.store / "gate").glob("*/verdicts.json"):
            data = json.loads(vfile.read_text())
            data["verdicts"][d1]["crop_sha256"] = "0" * 64
            vfile.write_text(json.dumps(data))
        run = self.gate()
        self.assertIn("Carried 1 verdict(s)", run.stdout)
        self.assertIn(f"{d1}: no verdict yet", run.stdout)


class ScopeRequestTests(StudioBase):
    """A change the user asks for (kind scope), like a new date, is not a miss: no lesson, and a small edit is enough."""

    def small_edit(self, kind, quote=None):
        self.init()
        self.approve_poster(self.poster(card=False))
        self.assertEqual(self.gate().returncode, 0)
        extra = ["--quote", quote] if quote else []
        did = self.ok("defect", "add", "--deliverable", "poster", "--bbox", "20,20,180,120", "--kind", kind,
                      "--note", "change the date", *extra).stdout.split()[2]
        img = Image.open(self.project / "poster.png").convert("RGB")
        ImageDraw.Draw(img).rectangle((60, 60, 64, 64), fill=(0, 0, 0))  # 25 px in a 16,000 px box: about 0.2-1%
        ImageDraw.Draw(img).rectangle((70, 60, 74, 72), fill=(0, 0, 0))
        img.save(self.project / "poster.png")
        self.approve_poster(self.project / "poster.png")
        self.ok("defect", "close", "--id", did, "--status", "resolved", "--note", "date updated")
        run = self.gate()
        return did, run

    def test_scope_request_needs_no_lesson_and_passes_with_a_small_edit(self):
        did, run = self.small_edit("scope", quote="change the deadline to the 25th")
        self.assertNotIn("needs_lesson", self.defects()[0])
        self.assertNotIn("almost nothing changed", run.stdout)
        self.assertNotIn("has no lesson", run.stdout)

    def test_scope_without_the_users_words_gets_no_discount(self):
        did, run = self.small_edit("scope")
        self.assertTrue(self.defects()[0]["needs_lesson"])
        self.assertIn("almost nothing changed", run.stdout)

    def test_a_real_defect_still_needs_a_lesson_and_a_visible_fix(self):
        did, run = self.small_edit("artifact")
        self.assertTrue(self.defects()[0]["needs_lesson"])
        self.assertIn("almost nothing changed", run.stdout)
        self.assertIn("has no lesson", run.stdout)


class ConcurrencyAndLinkTests(StudioBase):
    def test_parallel_verdicts_are_all_kept(self):
        self.init()
        self.approve_poster(self.poster(card=True, dots=True))
        ids = [self.defect(list(b)) for b in DOTS]
        self.approve_poster(self.poster(card=True, dots=False))
        for did in ids:
            self.ok("defect", "close", "--id", did, "--status", "resolved", "--note", "removed")
        run = self.run_id(self.gate())
        env = dict(os.environ, IMAGE_STUDIO_HOME=str(self.home))
        procs = [subprocess.Popen([sys.executable, str(SCRIPT), "verdict", "--run", run, "--id", did, "--status", "pass",
                                   "--evidence", "dot is gone at 100%"], cwd=str(self.project), env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for did in ids]
        for proc in procs: self.assertEqual(proc.wait(), 0)
        data = json.loads((self.run_dir(run) / "verdicts.json").read_text())
        self.assertEqual(sorted(data["verdicts"]), sorted(ids))

    def test_taste_with_brand_keeps_the_deliverable_link(self):
        self.init()
        self.approve_poster(self.poster())
        self.ok("taste", "add", "--brand", "zeta", "--deliverable", "poster", "--note", "warm rim light")
        item = json.loads((self.home / "brands" / "zeta" / "taste.jsonl").read_text().splitlines()[0])
        self.assertEqual(item["deliverable"], "poster")


class DefectMapTests(StudioBase):
    """map draws every open defect on one image, so the user confirms all findings in one round."""

    def test_map_marks_open_defects_only(self):
        self.init(); self.approve_poster(self.poster())
        d1 = self.defect([20, 20, 80, 80], kind="artifact", note="mushy blob", source="agent")
        d2 = self.defect([100, 30, 180, 120], kind="seam", note="hard edge", source="agent")
        self.ok("defect", "close", "--id", d2, "--status", "wontfix", "--note", "not a problem", "--quote", "cái 2 ko sao")
        out = self.project / "map.png"
        run = self.ok("map", "--deliverable", "poster", "--out", out)
        self.assertIn(d1, run.stdout); self.assertNotIn(d2 + " ", run.stdout)
        with Image.open(out) as raw: img = raw.convert("RGB")
        self.assertEqual(img.size, (200, 150))
        self.assertEqual(img.getpixel((20, 50)), (255, 0, 0))     # D1 outline
        self.assertEqual(img.getpixel((179, 75)), (255, 255, 255))  # closed D2 not drawn

    def test_map_rejects_file_of_other_size(self):
        self.init(); self.approve_poster(self.poster())
        other = self.project / "small.png"; Image.new("RGB", (50, 50)).save(other)
        run = self.run_cli("map", "--deliverable", "poster", "--file", other, "--out", self.project / "m.png")
        self.assertEqual(run.returncode, 2); self.assertIn("size", run.stderr)


class EditCheckTests(StudioBase):
    """edit-check: changes outside the edit box and one before|after|changes view, without a store."""

    def images(self, leak=False):
        before = Image.new("RGB", (200, 150), (90, 120, 150)); before.save(self.project / "a.png")
        after = before.copy(); draw = ImageDraw.Draw(after)
        draw.rectangle((60, 40, 120, 100), fill=(200, 180, 40))
        if leak: draw.rectangle((150, 120, 159, 129), fill=(0, 0, 0))
        after.save(self.project / "b.png")

    def test_clean_edit_passes_and_writes_view(self):
        self.images()
        run = self.ok("edit-check", "--before", "a.png", "--after", "b.png", "--bbox", "50,30,130,110", "--out", "v.png")
        self.assertIn("outside the box: 0", run.stdout)
        with Image.open(self.project / "v.png") as view: view.load()
        self.assertEqual(view.size[1], 80 + 2 * 24)  # box plus the default 24 px ring
        self.assertEqual(view.size[0], 3 * (80 + 2 * 24))

    def test_change_outside_box_fails(self):
        self.images(leak=True)
        run = self.run_cli("edit-check", "--before", "a.png", "--after", "b.png", "--bbox", "50,30,130,110", "--out", "v.png")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("outside the box: 100", run.stdout)
        self.assertIn("150,120,160,130", run.stdout)

    def test_size_mismatch_is_bad_input(self):
        self.images(); Image.new("RGB", (10, 10)).save(self.project / "c.png")
        run = self.run_cli("edit-check", "--before", "a.png", "--after", "c.png", "--bbox", "1,1,5,5")
        self.assertEqual(run.returncode, 2); self.assertIn("size", run.stderr)


class LongChatTests(StudioBase):
    """A chat that carried earlier jobs resends their whole history on every step; the card says so."""

    def card(self, size):
        transcript = self.project / "rollout.jsonl"
        with open(transcript, "wb") as fh: fh.truncate(size)  # sparse file, no disk use
        run = self.run_cli("hook", "session-start", stdin=json.dumps({"cwd": str(self.project), "transcript_path": str(transcript)}))
        return run.stdout

    def test_long_chat_gets_a_new_chat_hint(self):
        self.init()
        mod = load_module()
        self.assertIn("start a new chat", self.card(mod.LONG_CHAT_BYTES + 1))
        self.assertNotIn("start a new chat", self.card(1000))


class BatchVerdictTests(StudioBase):
    """verdict --from records every defect of a gate run in one call; one bad entry writes nothing."""

    def setUp(self):
        super().setUp()
        self.init(); self.approve_poster(self.poster(dots=True))
        for box in DOTS: self.defect(box, kind="artifact")
        self.approve_poster(self.poster())
        for i in (1, 2, 3): self.ok("defect", "close", "--id", f"D{i}", "--status", "resolved", "--note", "fixed earlier")

    def write(self, entries):
        path = self.project / "verdicts-in.json"; path.write_text(json.dumps(entries)); return path

    def test_one_call_records_all_and_gate_passes(self):
        run_id = self.run_id(self.gate())
        entries = [{"id": f"D{i}", "status": "pass", "evidence": f"D{i} region clean at 100%"} for i in (1, 2, 3)]
        run = self.ok("verdict", "--run", run_id, "--from", self.write(entries), "--reviewer", "independent")
        self.assertIn("3 verdicts recorded", run.stdout)
        self.assertEqual(self.gate("--run", run_id).returncode, 0)

    def test_bad_entry_writes_nothing(self):
        run_id = self.run_id(self.gate())
        entries = [{"id": "D1", "status": "pass", "evidence": "D1 region clean at 100%"},
                   {"id": "D9", "status": "pass", "evidence": "no such defect here"}]
        run = self.run_cli("verdict", "--run", run_id, "--from", self.write(entries))
        self.assertEqual(run.returncode, 2); self.assertIn("D9", run.stderr)
        self.assertFalse((self.run_dir(run_id) / "verdicts.json").exists())

    def test_from_and_id_are_exclusive(self):
        run_id = self.run_id(self.gate())
        run = self.run_cli("verdict", "--run", run_id, "--from", self.write([]), "--id", "D1")
        self.assertEqual(run.returncode, 2)


class PrepareReviewTests(StudioBase):
    """prepare-review writes every hunt view in one call, tiles named by their corner."""

    def test_views_and_tile_offsets(self):
        img = Image.new("RGB", (300, 200))
        for x in range(300):
            for y in range(0, 200, 50): img.putpixel((x, y), (x % 256, y, 0))
        img.save(self.project / "in.png")
        Image.new("RGB", (150, 100), (9, 9, 9)).save(self.project / "approved.png")
        run = self.ok("prepare-review", "--image", "in.png", "--approved", "approved.png", "--out", "views")
        views = self.project / "views"
        names = sorted(p.name for p in views.iterdir())
        for name in ("edge-top.png", "edge-bottom.png", "edge-left.png", "edge-right.png", "gray.png", "thumb.png", "lineup.png"):
            self.assertIn(name, names)
        tiles = [n for n in names if n.startswith("tile-")]
        self.assertEqual(len(tiles), 6)
        for name in tiles:  # each tile equals the image crop at the corner in its name
            x, y = map(int, name[5:-4].split("_"))
            with Image.open(views / name) as tile:
                tile = tile.convert("RGB")
                self.assertEqual(tile.tobytes(), img.crop((x, y, x + tile.size[0], y + tile.size[1])).tobytes())
        self.assertIn("300x200", run.stdout)
        self.assertIn("tile-0_0.png", run.stdout)

    def test_small_and_thin_images_get_true_unique_tiles(self):
        for i, size in enumerate([(50, 30), (1, 1), (100, 7), (3001, 40)]):
            img = Image.new("RGB", size)
            for x in range(size[0]): img.putpixel((x, 0), (x % 256, 7, 9))
            img.save(self.project / "s.png")
            run = self.ok("prepare-review", "--image", "s.png", "--out", f"v{i}")
            tiles = [n for n in run.stdout.split() if n.startswith("tile-")]
            self.assertEqual(len(tiles), len(set(tiles)), (size, tiles))
            for name in tiles:
                x, y = map(int, name[5:-4].split("_"))
                self.assertGreaterEqual(min(x, y), 0, (size, name))
                with Image.open(self.project / f"v{i}" / name) as tile:
                    tile = tile.convert("RGB")
                    self.assertEqual(tile.tobytes(), img.crop((x, y, x + tile.size[0], y + tile.size[1])).tobytes())

    def test_existing_output_folder_with_files_is_refused(self):
        Image.new("RGB", (50, 50)).save(self.project / "in.png")
        (self.project / "views").mkdir(); (self.project / "views" / "old.png").write_text("x")
        run = self.run_cli("prepare-review", "--image", "in.png", "--out", "views")
        self.assertEqual(run.returncode, 2)


if __name__ == "__main__":
    unittest.main()
