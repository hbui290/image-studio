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
        self.assertEqual(len(skill_names()), 9)
        for name in skill_names():
            meta = frontmatter(SKILLS / name / "SKILL.md")
            self.assertEqual(meta.get("name"), name)
            self.assertGreater(len(meta.get("description", "")), 40, name)

    def test_repository_links_resolve(self):
        self.assertEqual(broken_links(ROOT), [])

    def test_manifests_agree_on_name_and_version(self):
        claude = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text())
        codex = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
        self.assertEqual(claude["name"], "image-studio")
        self.assertEqual(codex["name"], "image-studio")
        self.assertEqual(claude["version"], codex["version"])
        claude_market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
        codex_market = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual((ROOT / claude_market["plugins"][0]["source"]).resolve(), PLUGIN)
        self.assertEqual((ROOT / codex_market["plugins"][0]["source"]["path"]).resolve(), PLUGIN)

    def test_repo_skill_links_point_at_plugin_skills(self):
        for name in skill_names():
            link = ROOT / ".claude/skills" / name
            self.assertTrue(link.is_symlink(), name)
            self.assertEqual(link.resolve(), (SKILLS / name).resolve())

    def test_standalone_install_keeps_links_working(self):
        spec = importlib.util.spec_from_file_location("installer", ROOT / "scripts/install.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(sorted(module.NAMES), skill_names())
        with tempfile.TemporaryDirectory() as tmp:
            module.install(SKILLS, Path(tmp))
            self.assertEqual(broken_links(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
