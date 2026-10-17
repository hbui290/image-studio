"""Regression tests for validate_spec.py, reconstruct.py and visual-map.html input checks."""
import copy
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deps import needs_jsonschema, needs_pillow  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins/image-studio/skills"
VALIDATE = SKILLS / "image-edit-map/scripts/validate_spec.py"
EDIT_MAP_EXAMPLE = SKILLS / "image-edit-map/examples/image-spec.example.json"
RECON_SKILL = SKILLS / "image-reconstruction"
NODE = shutil.which("node")
# Mirrors the page's import: parse the text (duplicate keys, number lexemes), then validate and compile.
RUNNER = """
const page = require(process.argv[2]);
const {texts, schema} = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(texts.map(text => {
  try { const spec = page.parseJSON ? page.parseJSON(text) : JSON.parse(text); page.compileSpec(spec, schema); return {}; }
  catch (error) { return {error: error.message}; }
})));
"""


def load_reconstruct():
    spec = importlib.util.spec_from_file_location("reconstruct_spec_page", RECON_SKILL / "scripts/reconstruct.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rc = load_reconstruct()


def run(*args):
    return subprocess.run([sys.executable, str(VALIDATE), *map(str, args)], capture_output=True, text=True)


def edit_map_example():
    return json.loads(EDIT_MAP_EXAMPLE.read_text(encoding="utf-8"))


def vellum():
    return json.loads((RECON_SKILL / "examples/vellum.reconstruction.json").read_text(encoding="utf-8"))


def vellum_with_edit():
    spec = vellum()
    spec["selections"] = [{"target_id": "A-05", "action": "restyle", "properties": ["appearance.color"],
                           "instruction": "Make it deep green.", "destination_bbox": None, "reference_ids": [],
                           "preserve": [], "allow": []}]
    spec["review_flags"] = rc.review_flags_for(spec)
    return spec


class SpecFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data, name="spec.json"):
        path = self.dir / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path


@needs_jsonschema
@needs_pillow
class ValidateSpecDimensions(SpecFile):
    def image(self):
        from PIL import Image
        path = self.dir / "source.png"
        Image.new("RGB", (1600, 900)).save(path)
        return path

    def test_missing_dimensions_are_not_reported_as_matching(self):
        missing = edit_map_example()
        for key in ("width_px", "height_px"):
            del missing["images"][0]["metadata"][key]
        unknown = edit_map_example()
        for key in ("width_px", "height_px"):
            unknown["images"][0]["metadata"][key] = {"value": None, "basis": "unknown", "confidence": "unknown",
                                                     "note": "Not measured."}
        for label, spec in (("missing", missing), ("null", unknown)):
            result = run(self.write(spec), "--image", self.image())
            self.assertEqual(result.returncode, 0, label + result.stderr)
            self.assertNotIn("match decoded image", result.stdout, label)
            self.assertIn("not verified", result.stdout, label)

    def test_reported_dimensions_still_claim_a_match(self):
        result = run(EDIT_MAP_EXAMPLE, "--image", self.image())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reported dimensions match decoded image", result.stdout)

    def test_image_selection_errors_exit_2(self):
        two = edit_map_example()
        second = copy.deepcopy(two["images"][0])
        second["id"] = "B"
        two["images"].append(second)
        two["picture_types"].append(dict(copy.deepcopy(two["picture_types"][0]), target_id="B"))
        two_path = self.write(two, "two.json")
        self.assertEqual(run(two_path).returncode, 0)  # the spec itself is valid
        for label, args in (("unknown id", (EDIT_MAP_EXAMPLE, "--image", self.image(), "--image-id", "Z")),
                            ("missing id", (two_path, "--image", self.image()))):
            result = run(*args)
            self.assertEqual(result.returncode, 2, label)
            self.assertIn("--image-id", result.stderr, label)
            self.assertNotIn("Traceback", result.stderr, label)


@needs_jsonschema
class ValidateSpecRules(SpecFile):
    def test_unknown_observation_needs_a_reason(self):
        spec = edit_map_example()
        spec["images"][0]["metadata"]["alpha_present"]["note"] = "  "
        result = run(self.write(spec))
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_section_id_carries_its_image_prefix(self):
        spec = edit_map_example()
        spec["sections"][0]["id"] = "B:S9"
        for element in spec["elements"]:
            element["section_id"] = "B:S9"
        result = run(self.write(spec))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("B:S9", result.stderr)

    def test_shipped_examples_still_pass(self):
        for path in (EDIT_MAP_EXAMPLE, ROOT / "examples/image-reverse-engineer/image-spec.json"):
            result = run(path)
            self.assertEqual(result.returncode, 0, str(path) + result.stderr)


class ReconstructScript(unittest.TestCase):
    def test_edit_mode_needs_a_target_path(self):
        spec = vellum_with_edit()
        spec["source_images"][0]["path"] = None
        rc.validate(spec)
        rc.compile_spec(copy.deepcopy(spec))  # full mode only warns
        with self.assertRaises(rc.Invalid):
            rc.compile_spec(spec, "edit")

    def test_lone_surrogate_fails_validation(self):
        value = copy.deepcopy(vellum())
        value["elements"][0]["name"] = "\ud800"
        key = copy.deepcopy(vellum())
        key["elements"][0]["appearance"]["\udc00"] = key["elements"][0]["appearance"]["color"]
        for label, spec in (("value", value), ("key", key)):
            with self.assertRaises(rc.Invalid, msg=label):
                rc.validate(spec)


@unittest.skipUnless(NODE, "node is not installed")
class VisualMapRejects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        html = (RECON_SKILL / "visual-map.html").read_text(encoding="utf-8")
        cls.schema = json.loads(re.search(r'<script type="application/json" id="contract">(.*?)</script>', html, re.S).group(1))
        cls.tmp = tempfile.TemporaryDirectory()
        cls.page = Path(cls.tmp.name) / "page.js"
        cls.page.write_text(html.rsplit("<script>", 1)[1].split("</script>")[0], encoding="utf-8")
        cls.runner = Path(cls.tmp.name) / "run.js"
        cls.runner.write_text(RUNNER, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def page_results(self, texts):
        run = subprocess.run([NODE, str(self.runner), str(self.page)], input=json.dumps({"texts": texts, "schema": self.schema}),
                             capture_output=True, text=True, check=True)
        return json.loads(run.stdout)

    def script_rejects(self, text):
        path = Path(self.tmp.name) / "case.json"
        path.write_text(text, encoding="utf-8")
        try:
            rc.validate(rc.read_json(path))
        except rc.Invalid:
            return True
        return False

    def assert_both_reject(self, cases):
        texts = [text for _, text in cases]
        for (label, text), page in zip(cases, self.page_results(texts)):
            self.assertTrue(self.script_rejects(text), label)
            self.assertIn("error", page, label)

    def test_baseline_is_accepted(self):
        self.assertEqual(self.page_results([json.dumps(vellum())]), [{}])

    def test_inherited_property_names(self):
        top = vellum()
        top["constructor"] = "x"
        element = vellum()
        element["elements"][0]["toString"] = 1
        endpoints = vellum()
        endpoints["relations"][0].update(from_id="constructor", to_id="toString")
        proto = json.dumps(vellum())
        proto = '{"__proto__": {"a": 1}, ' + proto[1:]
        self.assert_both_reject([("constructor", json.dumps(top)), ("toString", json.dumps(element)),
                                 ("relation endpoints", json.dumps(endpoints)), ("__proto__", proto)])

    def test_integer_written_as_float(self):
        revision = vellum()
        revision["revision"] = 1.0
        width = vellum()
        width["intent"]["output"]["width_px"] = 1122.0
        exponent = json.dumps(vellum()).replace('"revision": 1,', '"revision": 1e0,', 1)
        self.assertIn("1e0", exponent)
        self.assert_both_reject([("revision 1.0", json.dumps(revision)), ("width 1122.0", json.dumps(width)),
                                 ("revision 1e0", exponent)])

    def test_lone_surrogate(self):
        spec = vellum()
        spec["elements"][0]["name"] = "\ud800"
        self.assert_both_reject([("lone surrogate", json.dumps(spec))])

    def test_edit_mode_needs_a_target_path(self):
        code = ("const p=require(process.argv[1]);const t=s=>({id:'A',role:'target',path:s});"
                "console.log(JSON.stringify([p.editTarget([t(null)]),p.editTarget([t('a.png')])]))")
        run = subprocess.run([NODE, "-e", code, str(self.page)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), [False, True])


if __name__ == "__main__":
    unittest.main()
