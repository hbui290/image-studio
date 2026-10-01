# Image Studio: repo rules

This repo is a plugin for Claude Code and Codex. The plugin contains 10 skills in `plugins/image-studio/skills/` and one reviewer agent in `plugins/image-studio/agents/`. Users receive only the `plugins/image-studio/` folder, so a skill must not depend on files outside it unless it says "from a repo checkout".

## Attribution (do not change)

- `LICENSE` line 3 credits `codejunkie99` and `NOTICE` lists the parts taken from `codejunkie99/image-loop`. This is the owner's former team's work and the MIT license requires the notice. Never remove, hide, or reword that attribution. Adding new entries to `NOTICE` is fine.
- Never push to any `codejunkie99/*` repository.

## Code

- Scripts must run on Python 3.9: no `X | Y` type unions, no `match`. The CI job on Python 3.9 is the final check.
- Dependencies are Pillow and jsonschema only. Do not add others without asking.
- Bad input ends in a clear message and exit code 2, never a traceback. Exit codes, flags, output file names, and JSON field names must match what the docs say.
- Every behavior fix gets a regression test in `tests/` that fails before the fix.
- Run the tests:
  ```bash
  uv run --with pillow --with jsonschema python3 -m unittest discover -s tests
  ```
- `image-reconstruction/visual-map.html` embeds copies of `references/reconstruction.schema.json` and the prompt compiler from `scripts/reconstruct.py`. When you change either one, update the copy in the page in the same change; `tests/test_visual_map.py` fails if they drift.

## Docs

- Each skill folder has `SKILL.md`, which should give: when to use it and when to use a sibling skill instead, required tools, numbered steps, exact commands, outputs, and stop conditions.
- Inside skill files, name other skills by their bare name and a relative link to `../<skill>/SKILL.md`. The prefixed form `$image-studio:<skill>` or `/image-studio:<skill>` belongs only in `README.md`.
- To show how to run a script, write `python3 <skills>/<skill>/scripts/<name>.py ...` and give the dependency install once with `uv run --with ...`, plus `pip install` as a fallback. Do not add more install styles.
- Use sentence case for headings ("Image verification", not "Image Verification").
- Do not invent a new ID style. Reuse the style the skill already uses.
- Every relative link must resolve. Every external tool gets its official URL.
- When you change a version, change it in every manifest that has one, at once (`.claude-plugin/marketplace.json`, `plugins/image-studio/.claude-plugin/plugin.json`, `plugins/image-studio/.codex-plugin/plugin.json`), and add an entry to `CHANGELOG.md`. Installed copies only update when the version changes.

## Before calling a change done

- The tests pass.
- `claude plugin validate --strict .` and `claude plugin validate --strict plugins/image-studio` both pass.
- Pushing, tagging, and publishing require the owner's approval each time.
