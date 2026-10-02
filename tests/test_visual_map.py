"""visual-map.html must accept the same JSON and build the same prompts as reconstruct.py. Needs node; skips without it."""

import copy
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/image-studio/skills/image-reconstruction"
NODE = shutil.which("node")
RUNNER = """
const page = require(process.argv[2]);
const {spec, schema} = JSON.parse(require('fs').readFileSync(0, 'utf8'));
try { const c = page.compileSpec(spec, schema); console.log(JSON.stringify({full: c.rendering_prompt, edit: c.edit_prompt})); }
catch (error) { console.log(JSON.stringify({error: error.message})); }
"""


def load_reconstruct():
    spec = importlib.util.spec_from_file_location("reconstruct", SKILL / "scripts/reconstruct.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(NODE, "node is not installed")
class VisualMapParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (SKILL / "visual-map.html").read_text(encoding="utf-8")
        cls.schema = json.loads((SKILL / "references/reconstruction.schema.json").read_text(encoding="utf-8"))
        cls.vellum = json.loads((SKILL / "examples/vellum.reconstruction.json").read_text(encoding="utf-8"))
        cls.rc = load_reconstruct()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.page = Path(cls.tmp.name) / "page.js"
        cls.page.write_text(cls.html.rsplit("<script>", 1)[1].split("</script>")[0], encoding="utf-8")
        (Path(cls.tmp.name) / "run.js").write_text(RUNNER, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def embedded(self, ident):
        found = re.search(r'<script type="application/json" id="%s">(.*?)</script>' % ident, self.html, re.S)
        return json.loads(found.group(1))

    def js(self, spec):
        run = subprocess.run([NODE, str(Path(self.tmp.name) / "run.js"), str(self.page)], input=json.dumps({"spec": spec, "schema": self.embedded("contract")}),
                             capture_output=True, text=True, check=True)
        return json.loads(run.stdout)

    def edited_vellum(self):
        spec = copy.deepcopy(self.vellum)
        spec["selections"] = [
            {"target_id": "A-05", "action": "restyle", "properties": ["appearance.color"], "instruction": "Make it deep green.",
             "destination_bbox": None, "reference_ids": [], "preserve": ["shape"], "allow": []},
            {"target_id": "A-15", "action": "move", "properties": ["bbox"], "instruction": "Move it slightly left.",
             "destination_bbox": [0.05, 0.05, 0.1, 0.1], "reference_ids": [], "preserve": [], "allow": []}]
        return spec

    def test_embedded_copies_match_their_files(self):
        self.assertEqual(self.embedded("contract"), self.schema)
        spec = self.embedded("initial-spec")
        spec["source_images"][0]["path"] = "../" + spec["source_images"][0]["path"]  # the page sits one folder up
        self.assertEqual(spec, self.vellum)

    def test_prompts_match_reconstruct_py(self):
        synthetic = json.loads((SKILL / "examples/synthetic-scene.json").read_text(encoding="utf-8"))
        for label, spec in (("vellum", self.vellum), ("edited vellum", self.edited_vellum()), ("synthetic", synthetic)):
            page = self.js(spec)
            self.assertNotIn("error", page, label)
            self.assertEqual(page["full"], self.rc.compile_spec(spec)["rendering_prompt"], label)
            if any(s["action"] != "keep" for s in spec["selections"]) and any(
                    s["role"] == "target" and s["selected_for_use"] for s in spec["source_images"]):
                self.assertEqual(page["edit"], self.rc.compile_spec(spec, "edit")["rendering_prompt"], label)

    def test_edit_prompt_keeps_protected_details(self):
        edit = self.js(self.edited_vellum())["edit"]
        for section in ("PRESERVE", "Reconcile before generating:", "REQUIRED RESULT"):
            self.assertIn("\n" + section, edit)

    def test_page_rejects_what_the_script_rejects(self):
        blank = copy.deepcopy(self.vellum)
        blank["elements"][0]["name"] = "   "
        keep_props = copy.deepcopy(self.vellum)
        keep_props["selections"] = [{"target_id": "A-05", "action": "keep", "properties": ["text"], "instruction": "",
                                     "destination_bbox": None, "reference_ids": [], "preserve": [], "allow": []}]
        move_color = self.edited_vellum()
        move_color["selections"][1]["properties"] = ["bbox", "appearance.color"]
        casefold = self.edited_vellum()
        casefold["selections"][0]["preserve"], casefold["selections"][0]["allow"] = ["Straße"], ["STRASSE"]
        for label, spec in (("blank name", blank), ("keep with properties", keep_props),
                            ("move with color", move_color), ("casefold overlap", casefold)):
            with self.assertRaises(self.rc.Invalid, msg=label):
                self.rc.validate(spec)
            self.assertIn("error", self.js(spec), label)


if __name__ == "__main__":
    unittest.main()
