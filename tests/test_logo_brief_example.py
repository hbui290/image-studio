"""Tests for the reusable per-occurrence logo brief example."""

import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
BRIEF_PATH = ROOT / "examples/image-repair/logo-brief.json"
SCHEMA_PATH = ROOT / "plugins/image-studio/skills/image-loop/references/brief.schema.json"
GATES_PATH = ROOT / "plugins/image-studio/skills/image-repair/references/repair-rules.md"


class LogoBriefExampleTest(unittest.TestCase):
    def setUp(self):
        self.brief = json.loads(BRIEF_PATH.read_text(encoding="utf-8"))
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_example_validates_against_brief_schema(self):
        validator = Draft202012Validator(self.schema)
        errors = list(validator.iter_errors(self.brief))
        self.assertEqual(errors, [])

    def test_brief_has_distinct_criterion_ids(self):
        ids = [c["id"] for c in self.brief["criteria"]]
        self.assertEqual(len(ids), len(set(ids)))
        for cid in ids:
            self.assertEqual(cid, cid.strip())

    def test_every_occurrence_has_six_checks_and_protected_area(self):
        occurrences = ["pack front", "card front", "card back"]
        criteria = self.brief["criteria"]

        check_signatures = {
            "approved master": lambda c: "approved master" in c["requirement"].lower(),
            "black star and d tail": lambda c: "black star" in c["requirement"].lower() and "d tail" in c["requirement"].lower(),
            "old logo removed": lambda c: "old logo" in c["requirement"].lower() and "removed" in c["requirement"].lower(),
            "no patch or halo": lambda c: "patch or halo" in c["requirement"].lower(),
            "clean alpha edge": lambda c: "alpha edge" in c["requirement"].lower() and "clean" in c["requirement"].lower(),
            "not stacked twice": lambda c: "stacked" in c["requirement"].lower() and "twice" in c["requirement"].lower(),
        }

        for occ in occurrences:
            prefix = occ.replace(" ", "_")
            occ_criteria = [
                c for c in criteria
                if occ in c["target"].lower() or occ in c["requirement"].lower() or c["id"].startswith(prefix)
            ]
            self.assertGreaterEqual(len(occ_criteria), 7, f"Expected at least 7 criteria for {occ}")

            occ_ids = [c["id"] for c in occ_criteria]
            self.assertEqual(len(occ_ids), len(set(occ_ids)))
            for cid in occ_ids:
                self.assertTrue(cid.startswith(prefix), f"Criterion ID {cid} should start with {prefix}")

            requested_criteria = [c for c in occ_criteria if c["kind"] == "requested"]
            for check_name, matches in check_signatures.items():
                matching = [c for c in requested_criteria if matches(c)]
                self.assertEqual(
                    len(matching), 1,
                    f"Occurrence '{occ}' should have exactly one check for '{check_name}', found {len(matching)}"
                )

            protected_criteria = [c for c in occ_criteria if c["kind"] == "protected"]
            self.assertGreaterEqual(
                len(protected_criteria), 1,
                f"Occurrence '{occ}' should have protected criteria for surrounding area"
            )
            for p in protected_criteria:
                self.assertIn("preserve", p["requirement"].lower())

    def test_brand_repair_gates_links_to_example_from_repo_checkout(self):
        content = GATES_PATH.read_text(encoding="utf-8")
        self.assertIn("from a repo checkout", content.lower())
        self.assertIn("logo-brief.json", content)


if __name__ == "__main__":
    unittest.main()
