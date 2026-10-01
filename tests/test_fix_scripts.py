"""Regression tests for reconstruct.py, combine.py, advance.py and validate_spec.py fixes."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deps import needs_jsonschema, needs_pillow  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins/image-studio/skills"
RECON = SKILLS / "image-reconstruction/scripts/reconstruct.py"
COMBINE = SKILLS / "image-inspiration/scripts/combine.py"
ADVANCE = SKILLS / "image-inspiration/scripts/advance.py"
VALIDATE = SKILLS / "image-edit-map/scripts/validate_spec.py"
EXAMPLES = SKILLS / "image-reconstruction/examples"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recon = load("reconstruct_fix", RECON)
combine = load("combine_fix", COMBINE)


def run(script, *args):
    return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True)


def synthetic():
    return json.loads((EXAMPLES / "synthetic-scene.json").read_text())


def vellum_edit():
    """Vellum spec with one restyle on A-05, so some invariants are flagged and others are not."""
    spec = json.loads((EXAMPLES / "vellum.reconstruction.json").read_text())
    spec["elements"][1]["locked_properties"] = ["bbox"]  # an unedited element
    spec["selections"] = [{"target_id": "A-05", "action": "restyle", "properties": ["appearance.color"],
                           "instruction": "Change only the walnut cap to a charcoal-black finish.",
                           "destination_bbox": None, "reference_ids": [], "preserve": [], "allow": []}]
    spec["revision"] += 1
    spec["review_flags"] = recon.review_flags_for(spec)
    return spec


class TempDirCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write_json(self, name, data):
        path = self.dir / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path


class ReconstructOutputTests(TempDirCase):
    def test_output_refuses_existing_file_and_symlink_unless_force(self):  # bug 1
        spec = self.write_json("spec.json", synthetic())
        photo = self.dir / "photo.png"
        photo.write_bytes(b"precious image")
        result = run(RECON, "compile", spec, "--output", photo)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("--force", result.stderr)
        self.assertEqual(photo.read_bytes(), b"precious image")
        for target in (photo, self.dir / "missing.png"):  # live and dangling links
            link = self.dir / ("link-" + target.name)
            link.symlink_to(target)
            result = run(RECON, "compile", spec, "--output", link)
            self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(photo.read_bytes(), b"precious image")
        self.assertFalse((self.dir / "missing.png").exists())
        fresh = self.dir / "fresh.txt"
        self.assertEqual(run(RECON, "compile", spec, "--output", fresh).returncode, 0)
        self.assertIn("RENDERING PROMPT", fresh.read_text())
        self.assertEqual(run(RECON, "compile", spec, "--output", fresh, "--force").returncode, 0)
        self.assertEqual(run(RECON, "compile", spec, "--output", photo, "--force").returncode, 0)
        self.assertIn("RENDERING PROMPT", photo.read_text())
        before = spec.read_text()
        result = run(RECON, "compile", spec, "--output", spec, "--force")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(spec.read_text(), before)

    def test_lone_surrogate_is_a_clean_error(self):  # bug 6
        data = synthetic()
        data["elements"][0]["name"] = "\ud800"
        spec = self.write_json("spec.json", data)
        out = self.dir / "out.txt"
        for extra in ([], ["--format", "json"], ["--output", out]):
            result = run(RECON, "compile", spec, *extra)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertIn("ERROR", result.stderr)
        self.assertFalse(out.exists())


class ReconstructPromptTests(unittest.TestCase):
    def test_flagged_invariants_stay_in_prompt_under_reconcile(self):  # bug 2
        spec = vellum_edit()
        flagged = spec["review_flags"]["invariant_ids"]
        self.assertTrue(flagged)
        spec["invariants"].append({"id": "P99", "target_ids": [], "origin": "user",
                                   "description": "GLOBAL_SENTINEL keep the paper grain."})
        spec["review_flags"] = recon.review_flags_for(spec)
        self.assertIn("P99", spec["review_flags"]["invariant_ids"])
        compiled = recon.compile_spec(spec)
        prompt = compiled["rendering_prompt"]
        self.assertIn("Reconcile before generating:", prompt)
        for item in spec["invariants"]:
            self.assertIn(item["description"], prompt)
        self.assertEqual(compiled["review_flags"]["invariant_ids"], spec["review_flags"]["invariant_ids"])

    def test_edit_mode_keeps_invariants_locks_and_hard_criteria(self):  # bug 3
        spec = vellum_edit()
        prompt = recon.compile_spec(spec, mode="edit")["rendering_prompt"]
        flagged = set(spec["review_flags"]["invariant_ids"])
        self.assertTrue(flagged and flagged != {i["id"] for i in spec["invariants"]})
        for item in spec["invariants"]:
            self.assertIn(item["description"], prompt)
        self.assertIn(spec["elements"][1]["id"], prompt.split("PRESERVE", 1)[1])
        hard = [c for c in spec["criteria"]["hard"] if c["id"] not in spec["review_flags"]["criterion_ids"]]
        self.assertTrue(hard)
        for criterion in hard:
            self.assertIn(criterion["description"], prompt)
        self.assertIn("charcoal-black", prompt)


@needs_jsonschema
class ReconstructSchemaTests(unittest.TestCase):
    def test_trailing_newline_ids_are_rejected(self):  # bug 4
        schema = recon.read_json(recon.SCHEMA_PATH)
        for definition, good in (("element", "A-01"), ("group", "A-G01"), ("source", "A")):
            rule = schema["$defs"][definition]["properties"]["id"]
            recon.schema_check(good, rule, schema)
            with self.assertRaises(recon.Invalid):
                recon.schema_check(good + "\n", rule, schema)

    def test_whitespace_only_text_is_rejected(self):  # bug 5
        for mutate in (lambda s: s["criteria"]["hard"][0].update(description="   "),
                       lambda s: s["invariants"][0].update(description=" \t\n"),
                       lambda s: s["criteria"]["hard"][0].update(check="  ")):
            spec = synthetic()
            mutate(spec)
            with self.assertRaises(recon.Invalid):
                recon.validate(spec)
        recon.validate(synthetic())


def board(axes=6, traits=30):
    template = json.loads((ROOT / "examples/image-inspiration/board.json").read_text())
    template["axes"] = {f"a{i}": [dict(template["axes"]["lighting"][0], id=f"a{i}:t{j}") for j in range(traits)]
                        for i in range(axes)}
    template["fixed"] = {}
    # Chain: trait j of one axis only fits trait j of the next, so exactly `traits` combinations are valid.
    template["incompatible"] = [[f"a{i}:t{j}", f"a{i+1}:t{k}"] for i in range(axes - 1)
                                for j in range(traits) for k in range(traits) if j != k]
    return template


class CombineTests(unittest.TestCase):
    def test_backtracking_finds_valid_combinations_in_constrained_space(self):  # bug 7
        result = combine.plan(board(), 4)
        self.assertEqual(len(result["combinations"]), 4)
        for c in result["combinations"]:
            self.assertEqual(len({t["id"].split(":t")[1] for t in c["recipe"].values()}), 1)

    def test_shortfall_note_states_whether_search_was_complete(self):  # bug 7
        b = board()
        b["incompatible"] += [["a0:t%d" % j, "a1:t%d" % j] for j in range(3, 30)]
        result = combine.plan(b, 4)
        self.assertEqual(len(result["combinations"]), 3)
        self.assertIn("Fewer", result["note"])
        self.assertIn("complete search", result["note"])


class LoaderTests(TempDirCase):
    DEEP = "[" * 100000 + "]" * 100000

    def deep_file(self):
        path = self.dir / "deep.json"
        path.write_text(self.DEEP)
        return path

    def bom_file(self, source):
        path = self.dir / ("bom-" + Path(source).name)
        path.write_bytes(b"\xef\xbb\xbf" + Path(source).read_bytes())
        return path

    def assert_clean_failure(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_deep_nesting_is_a_clean_error_everywhere(self):  # bug 8
        deep = self.deep_file()
        out = self.dir / "out.json"
        self.assert_clean_failure(run(RECON, "validate", deep))
        self.assert_clean_failure(run(COMBINE, deep, "--out", out))
        self.assert_clean_failure(run(ADVANCE, deep, "--out", out))
        self.assert_clean_failure(run(VALIDATE, deep))

    @needs_jsonschema
    def test_utf8_bom_is_accepted_everywhere(self):  # bug 8
        out = self.dir / "out.json"
        result = run(RECON, "validate", self.bom_file(EXAMPLES / "synthetic-scene.json"))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = run(COMBINE, self.bom_file(ROOT / "examples/image-inspiration/board.json"), "--out", out)
        self.assertEqual(result.returncode, 0, result.stderr)
        out.unlink()
        result = run(ADVANCE, self.bom_file(ROOT / "examples/image-inspiration/state-loop.json"), "--out", out)
        self.assertEqual(result.returncode, 0, result.stderr)
        spec = SKILLS / "image-edit-map/examples/image-spec.example.json"
        result = run(VALIDATE, self.bom_file(spec))
        self.assertEqual(result.returncode, 0, result.stderr)


@needs_jsonschema
@needs_pillow
class ValidateSpecImageTests(TempDirCase):
    def test_decompression_bomb_image_is_a_clean_error(self):  # bug 9
        from PIL import Image
        bomb = self.dir / "bomb.png"
        Image.new("1", (14000, 14000)).save(bomb)
        spec = SKILLS / "image-edit-map/examples/image-spec.example.json"
        result = run(VALIDATE, spec, "--image", bomb, "--image-id", "A")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("too large", result.stderr)


@needs_jsonschema
class ValidateSpecIdTests(TempDirCase):
    def test_element_id_must_match_image_and_number(self):
        spec = json.loads((SKILLS / "image-edit-map/examples/image-spec.example.json").read_text(encoding="utf-8"))
        self.assertEqual(run(VALIDATE, self.write_json("ok.json", spec)).returncode, 0)
        element = spec["elements"][0]
        element["number"] += 100  # id still says the old number
        result = run(VALIDATE, self.write_json("bad.json", spec))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(element["id"] + ": id must be", result.stdout + result.stderr)

    def test_deep_value_inside_a_valid_spec_is_a_clean_error(self):
        spec = json.loads((SKILLS / "image-edit-map/examples/image-spec.example.json").read_text(encoding="utf-8"))
        spec["images"][0]["metadata"]["width_px"]["value"] = "DEEP"
        path = self.dir / "deep.json"  # built as text: json.dumps itself overflows at this depth on Python 3.9
        path.write_text(json.dumps(spec).replace('"DEEP"', "[" * 985 + "]" * 985), encoding="utf-8")
        result = run(VALIDATE, path)
        self.assertIn(result.returncode, (0, 1, 2), result.stderr)  # newer Pythons may handle this depth
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
