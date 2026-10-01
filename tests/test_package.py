"""Package integrity: skill metadata, local links, manifests, and standalone install."""

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/image-studio"
SKILLS = PLUGIN / "skills"
LINK = re.compile(r"\]\(([^)\s]+)\)")


def skill_names():
    return sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md"))


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not match:
        return {}
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def broken_links(base):
    broken = []
    for doc in sorted(base.rglob("*.md")):
        for target in LINK.findall(doc.read_text(encoding="utf-8")):
            if re.match(r"[a-z]+:", target) or target.startswith("#"):
                continue
            path = (doc.parent / target.split("#")[0]).resolve()
            if not path.exists():
                broken.append(f"{doc.relative_to(base)} -> {target}")
    return broken


class PackageTest(unittest.TestCase):
    def test_every_skill_has_matching_name_and_description(self):
        self.assertEqual(len(skill_names()), 10)
        for name in skill_names():
            meta = frontmatter(SKILLS / name / "SKILL.md")
            self.assertEqual(meta.get("name"), name)
            self.assertGreater(len(meta.get("description", "")), 40, name)
            description = meta["description"]
            # An unquoted ": " breaks YAML, and hosts then load the skill with no metadata.
            self.assertTrue(": " not in description or description.startswith('"'), name)

    def test_repository_links_resolve(self):
        self.assertEqual(broken_links(ROOT), [])

    def test_manifests_agree_on_name_and_version(self):
        claude = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text())
        codex = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
        self.assertEqual(claude["name"], "image-studio")
        self.assertEqual(codex["name"], "image-studio")
        self.assertEqual(claude["version"], codex["version"])
        claude_market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
        self.assertEqual(claude_market["plugins"][0]["version"], claude["version"])
        codex_market = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual((ROOT / claude_market["plugins"][0]["source"]).resolve(), PLUGIN)
        self.assertEqual((ROOT / codex_market["plugins"][0]["source"]["path"]).resolve(), PLUGIN)

    def test_repo_has_no_duplicate_skill_trees(self):
        # A second tree (symlinks or stale copies) shows every skill twice once the plugin is installed.
        dupes = [p for p in ROOT.rglob("SKILL.md") if SKILLS not in p.parents and ".git" not in p.parts]
        self.assertEqual(dupes, [])

    def test_standalone_install_keeps_links_working(self):
        spec = importlib.util.spec_from_file_location("installer", ROOT / "scripts/install.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(sorted(module.NAMES), skill_names())
        with tempfile.TemporaryDirectory() as tmp:
            module.install(SKILLS, Path(tmp))
            self.assertEqual(broken_links(Path(tmp)), [])


SCRIPT_REF = re.compile(r"<skills>/([^\s`]+)")
OLD_TERMS = re.compile(r"(?<![\w-])(/reverse-engineer|\$reverse-engineer|/inspiration|\$inspiration)\b"
                       r"|\b(escalate|stop_file_checks|stop_limit|reject_protected)\b|display_name: \"Inspiration\"")


class DocsTest(unittest.TestCase):
    def skill_docs(self):
        for doc in sorted(SKILLS.rglob("*")):
            if doc.suffix in (".md", ".yaml"):
                yield doc, doc.relative_to(SKILLS).parts[0], doc.read_text(encoding="utf-8")

    def test_skill_commands_use_paths_that_exist_in_every_install(self):
        for doc, skill, text in self.skill_docs():
            self.assertNotIn("plugins/image-studio", text, doc)
            self.assertNotIn("<skill-dir>", text, doc)
            for ref in SCRIPT_REF.findall(text):
                self.assertTrue((SKILLS / ref).is_file(), f"{doc}: <skills>/{ref}")

    def test_no_bare_python_launcher(self):
        docs = list(self.skill_docs()) + [(ROOT / "README.md", None, (ROOT / "README.md").read_text())]
        for doc, _, text in docs:
            for line in text.splitlines():
                stripped = line.strip().strip("`|")
                self.assertFalse(re.match(r"python\s", stripped), f"{doc}: {line.strip()}")

    def test_no_retired_names(self):
        for doc, _, text in self.skill_docs():
            self.assertIsNone(OLD_TERMS.search(text), f"{doc}: {OLD_TERMS.search(text) and OLD_TERMS.search(text).group(0)}")

    def test_reviewer_instructions_ship_with_every_install(self):
        agent = (PLUGIN / "agents/image-reviewer.md").read_text().split("---\n", 2)[2].strip()
        self.assertIn(agent, (SKILLS / "image-verify/references/independent-review.md").read_text())

    def test_every_skill_has_codex_metadata(self):
        for name in skill_names():
            self.assertTrue((SKILLS / name / "agents/openai.yaml").is_file(), name)


if __name__ == "__main__":
    unittest.main()
