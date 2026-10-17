from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RemovalLearningGuidanceTests(unittest.TestCase):
    def test_object_removal_requires_a_residue_sweep_in_skill_and_history(self):
        skill = (ROOT / "plugins/image-studio/skills/image-repair/SKILL.md").read_text(encoding="utf-8").lower()
        history = (ROOT / "plugins/image-studio/skills/image-repair/references/repair-rules.md").read_text(encoding="utf-8").lower()

        for term in ("frame edge", "corner", "border", "glow", "color spill", "occlusion", "200%"):
            with self.subTest(term=term):
                self.assertIn(term, skill)
                self.assertIn(term, history)

        self.assertIn("no recognizable silhouette", skill)
        self.assertIn("only for a recognizable whole object is insufficient", history)


if __name__ == "__main__":
    unittest.main()
