---
name: image-edit-map
description: "Plan an edit with the user: numbered visual map of named elements, then an edit brief with preservation checks. Use when the user wants to change parts of an image and must pick targets. Not for JSON-only breakdown (image-reverse-engineer) or defect diagnosis (image-inspect)."
---

# Image edit map

Turn "change that bit" into an addressable edit, without design vocabulary.

Routing: read-only JSON breakdown → [image-reverse-engineer](../image-reverse-engineer/SKILL.md); rebuild a reference from a part inventory → [image-reconstruction](../image-reconstruction/SKILL.md); mix several references → [image-inspiration](../image-inspiration/SKILL.md); new image → [image-create](../image-create/SKILL.md); find defects → [image-inspect](../image-inspect/SKILL.md); masked local fix that keeps every other pixel → [image-repair](../image-repair/SKILL.md), audited by [image-verify](../image-verify/SKILL.md).

Run scripts; do not read their source - use `--help` for usage.

## Steps

0. **Memory:** if not already in context, run `python3 <skills>/image-verify/scripts/studio_state.py brief` (no store: `taste list` and `lesson list` instead); see [using the store in a skill](../image-verify/references/project-memory.md#using-the-store-in-a-skill). Read this file and each reference once per chat, and open each new result once.
1. **Inspect** every supplied image; ask for a missing one, never invent contents. Name the edit target and the references; read real dimensions from metadata, not a resized preview.
2. **Ask** at most three unanswered questions: what should change, what must stay, where it will be used. Skip any the brief already answers.
3. **Map** only when targets need a picture: number sections and elements on a separate copy ([ImageMagick](https://imagemagick.org) badges from source coordinates; normalized `[x, y, width, height]` boxes converted with the [box rule](../image-verify/references/candidate-audit.md#contract-and-review)) and show the legend. Read [mapping-and-prompts.md](references/mapping-and-prompts.md) only when drawing a map. Honor "just do this" or "skip the map".
4. **Explain** selection: "make #3 smaller", "change #5's font", "keep section B"; use `A:#3`/`B:#3` for several images. Read [controls.md](references/controls.md) and [workflow.md](references/workflow.md) only when the user asks what can be changed, uses a command such as `/lock`, or references conflict.
5. **Edit** once the target, property, change, and preserved details are clear: Codex `image_gen.imagegen` (Claude Code has no built-in generator: hand back the prepared prompt). Edit from the last accepted clean version, never the annotated map. A clear request authorizes the edit.
6. **Compare** the result with the clean source and the agreed constraints. Read [verification.md](references/verification.md) only before delivering a spec or an exact-preservation edit.
7. **Gate:** with a project store, run `gate --deliverable` once before telling the user it is done ([using the store in a skill](../image-verify/references/project-memory.md#using-the-store-in-a-skill)).
8. **Stop and ask** when a reference is missing, selected targets conflict, or no image editor is available (then hand back the prepared prompt).
9. **Deliver** the clean image, its actual dimensions, the changes, and any remaining mismatch. Say plainly what was not rendered or not verified.

For `/spec` or a saved manifest, follow [reverse-engineer.md](references/reverse-engineer.md) and validate:

```sh
python3 <skills>/image-edit-map/scripts/validate_spec.py image-spec.json --image <source image> [--image-id B]
```

Needs jsonschema (and Pillow for `--image`): `uv run --with pillow --with jsonschema python3 ...` ([uv](https://docs.astral.sh/uv/)) or `python3 -m pip install pillow jsonschema`. Exit codes: 0 passed (`PASS: ...`; dimensions "not verified" when the spec has none), 1 invalid spec or dimension mismatch, 2 missing/unreadable file, bad JSON, missing dependency, or a missing/unknown `--image-id`. JSON must follow [the schema](references/image-spec.schema.json). `<skills>` is the folder that holds the skill folders.
