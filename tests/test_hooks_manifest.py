"""The plugin's hooks file (plugins/image-studio/hooks/hooks.json) and the docs that describe it."""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/image-studio"
HOOKS = PLUGIN / "hooks/hooks.json"
SCRIPT = "skills/image-verify/scripts/studio_state.py"
LINK = re.compile(r"\]\(([^)\s]+)\)")
DOCS = [PLUGIN / "skills/image-verify/references/project-memory.md", ROOT / "README.md"] + [
    PLUGIN / "skills" / name / "SKILL.md"
    for name in ("image-repair", "image-verify", "image-loop", "image-edit-map", "image-enhance")]


def hook_commands():
    events = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]
    return {event: [h["command"] for group in groups for h in group["hooks"]] for event, groups in events.items()}


def run_command(command, root, path=None, stdin='{"stop_hook_active": false}'):
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT")}
    env.update(root)
    if path is not None:
        env["PATH"] = path
    return subprocess.run(["/bin/sh", "-c", command], input=stdin, capture_output=True, text=True, env=env)


class HooksManifestTest(unittest.TestCase):
    def test_hooks_file_has_session_start_prompt_and_stop_calling_the_state_script(self):
        commands = hook_commands()
        self.assertEqual(sorted(commands), ["SessionStart", "Stop", "UserPromptSubmit"])
        for event, mode in (("SessionStart", "hook session-start"), ("UserPromptSubmit", "hook prompt"), ("Stop", "hook stop")):
            self.assertEqual(len(commands[event]), 1, event)
            self.assertIn(SCRIPT, commands[event][0])
            self.assertIn(mode, commands[event][0])
            # Claude Code sets CLAUDE_PLUGIN_ROOT; Codex sets PLUGIN_ROOT (and CLAUDE_PLUGIN_ROOT).
            self.assertIn("${CLAUDE_PLUGIN_ROOT:-$PLUGIN_ROOT}", commands[event][0])

    @unittest.skipUnless(Path("/bin/sh").exists(), "needs a POSIX shell")
    def test_command_runs_the_script_from_either_root_variable(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / SCRIPT
            stub.parent.mkdir(parents=True)
            stub.write_text("import sys\nprint(' '.join(sys.argv[1:]) + ' ' + sys.stdin.read())\nsys.exit(3)\n")
            for name in ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT"):
                run = run_command(hook_commands()["Stop"][0], {name: tmp})
                self.assertEqual(run.returncode, 0, name)  # a failing script still never breaks the session
                self.assertIn('hook stop {"stop_hook_active": false}', run.stdout, name)

    @unittest.skipUnless(Path("/bin/sh").exists(), "needs a POSIX shell")
    def test_missing_script_or_python_exits_0_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            for command in sum(hook_commands().values(), []):
                for root, path in (({"CLAUDE_PLUGIN_ROOT": tmp}, None), ({}, None),
                                   ({"CLAUDE_PLUGIN_ROOT": str(PLUGIN)}, tmp)):  # PATH without python3
                    run = run_command(command, root, path)
                    self.assertEqual((run.returncode, run.stdout, run.stderr), (0, "", ""), (command, root, path))

    @unittest.skipUnless(Path("/bin/sh").exists(), "needs a POSIX shell")
    def test_every_mode_prints_one_json_object_both_hosts_accept(self):
        # Claude Code (code.claude.com/docs/en/hooks) and Codex (the output schemas embedded in codex-cli) both take
        # {"hookSpecificOutput": {"hookEventName": E, "additionalContext": T}} for SessionStart and UserPromptSubmit,
        # and {"decision": "block", "reason": T} for Stop. Codex's schemas forbid any other key.
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")
        script = PLUGIN / SCRIPT
        with tempfile.TemporaryDirectory() as tmp:
            project, home = Path(tmp) / "project", Path(tmp) / "home"
            project.mkdir()
            env = {k: v for k, v in os.environ.items() if k not in ("CODEX_THREAD_ID", "CODEX_SESSION_ID", "CLAUDE_CODE_SESSION_ID")}
            env["IMAGE_STUDIO_HOME"] = str(home)
            Image.new("RGB", (40, 30), (9, 9, 9)).save(project / "a.png")
            for args in (["init", "--project", str(project), "--brand", "acme"],
                         ["approve", "deliverable", "--name", "a", "--file", str(project / "a.png"), "--width", "40",
                          "--height", "30", "--format", "PNG"]):
                subprocess.run([sys.executable, str(script)] + args, check=True, capture_output=True, env=env, cwd=str(project))
            env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN)
            base = {"cwd": str(project), "session_id": "s1", "turn_id": "t1", "transcript_path": "", "model": "m",
                    "permission_mode": "default"}
            cases = {"SessionStart": dict(base, hook_event_name="SessionStart", source="startup"),
                     "UserPromptSubmit": dict(base, hook_event_name="UserPromptSubmit", prompt="logo bị lỗi ở ảnh a.png"),
                     "Stop": dict(base, hook_event_name="Stop", stop_hook_active=False, last_assistant_message="Done.")}
            for event, payload in cases.items():
                run = subprocess.run(["/bin/sh", "-c", hook_commands()[event][0]], input=json.dumps(payload),
                                     capture_output=True, text=True, env=env, cwd=str(project))
                self.assertEqual((run.returncode, run.stderr), (0, ""), event)
                out = json.loads(run.stdout)  # one JSON object, nothing else
                if event == "Stop":
                    self.assertEqual(sorted(out), ["decision", "reason"], out)
                    self.assertEqual(out["decision"], "block")
                    self.assertTrue(out["reason"].startswith("image-studio: "))
                else:
                    self.assertEqual(list(out), ["hookSpecificOutput"], out)
                    self.assertEqual(sorted(out["hookSpecificOutput"]), ["additionalContext", "hookEventName"])
                    self.assertEqual(out["hookSpecificOutput"]["hookEventName"], event)
                    self.assertTrue(out["hookSpecificOutput"]["additionalContext"].startswith("image-studio"), out)
                    self.assertLessEqual(len(out["hookSpecificOutput"]["additionalContext"]), 10000)  # Claude Code's cap

    def test_commands_share_one_form_and_timeout(self):
        events = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]
        handlers = {event: groups[0]["hooks"][0] for event, groups in events.items()}
        forms = {h["command"].replace(mode, "MODE") for h, mode in (
            (handlers["SessionStart"], "hook session-start"), (handlers["UserPromptSubmit"], "hook prompt"), (handlers["Stop"], "hook stop"))}
        self.assertEqual(len(forms), 1, forms)
        self.assertEqual({h.get("timeout") for h in handlers.values()}, {10})

    def test_script_exists_in_the_plugin(self):
        # Fails until studio_state.py is shipped; the hooks would then silently do nothing.
        self.assertTrue((PLUGIN / SCRIPT).is_file())

    def test_hooks_are_auto_discovered_not_declared_twice(self):
        # Both hosts load hooks/hooks.json by default; Claude Code merges a declared file with it.
        for manifest in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
            self.assertNotIn("hooks", json.loads((PLUGIN / manifest).read_text()), manifest)

    def test_project_memory_docs_links_resolve(self):
        broken = []
        for doc in DOCS:
            text = doc.read_text(encoding="utf-8")
            for target in LINK.findall(text):
                if re.match(r"[a-z]+:", target) or target.startswith("#"):
                    continue
                path, _, anchor = target.partition("#")
                resolved = (doc.parent / path).resolve()
                if not resolved.exists():
                    broken.append(f"{doc.name} -> {target}")
                elif anchor and resolved.suffix == ".md":
                    headings = re.findall(r"^#+ (.+)$", resolved.read_text(encoding="utf-8"), re.M)
                    slugs = {re.sub(r"[^\w\- ]", "", h.lower()).strip().replace(" ", "-") for h in headings}
                    if anchor not in slugs:
                        broken.append(f"{doc.name} -> {target} (no heading)")
        self.assertEqual(broken, [])

    def test_gated_skills_load_memory_first_and_gate_last(self):
        for doc in DOCS[2:]:
            text = doc.read_text(encoding="utf-8")
            self.assertIn("studio_state.py brief", text, doc)
            self.assertIn("gate --deliverable", text, doc)
            self.assertIn("project-memory.md", text, doc)


if __name__ == "__main__":
    unittest.main()
