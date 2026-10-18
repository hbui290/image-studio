---
name: image-create
description: "Create an image, generate hero art, make an illustration, make a product scene, or generate from references: generate a new raster image in one pass from a brief and role-assigned references. Hand off to image-verify or image-loop."
---

# Image creation

Generate a new image with controlled composition, identity, and delivery size in one pass.

Routing: For multi-round generation/repairs use [image-loop](../image-loop/SKILL.md); for local fixes use [image-repair](../image-repair/SKILL.md); for mixing inspirations use [image-inspiration](../image-inspiration/SKILL.md).

## Operational checklist

0. **Memory and chat:** Run `python3 <skills>/image-verify/scripts/studio_state.py taste list --brand <brand>` and `lesson list` once. If this chat already handled another job, suggest the user start a new chat for this one: every step resends the whole history, and the store, lessons, and taste carry the memory. Read this file and each reference once per chat, and open each new result once.
1. **Requirements:** Use the host image generation tool under its own instructions (Codex: `image_gen.imagegen`; Claude Code has none built in, so use a configured image tool or hand back the prompt); never substitute another provider without stating so.
2. **Brief:** Define image job, canvas size, medium, subject, composition, copy space, output format, and required checks. If no source image exists, treat the brief as intent, not reconstructed fact.
   - **Style first:** before the first full image, settle the medium and rendering (for example 2D or 2.5D painted, not a 3D render) from the user's taste notes and the brand's approved references. With neither, make two or three small drafts in different renderings, let the user pick, and record the pick with `taste add --aspect style`.
   - **Layers:** text, numbers, and logos are never generated. Generate the background without them; when the subject's size or position may change (banners, social posts), generate the subject as its own cutout with `transparent_background`. Place the subject, the logo file from `brand show`, and every line of text with `compose_layers.py`, so changing a word, the logo position, or the subject's size is an edit to `layout.json` and one run (seconds), not a new generation:
     ```bash
     python3 <skills>/image-create/scripts/compose_layers.py layout.json --out final.png
     ```
     The layout format is in the script's `--help`. It needs Pillow: `uv run --with pillow python3 ...` ([uv](https://docs.astral.sh/uv/)) or `python3 -m pip install pillow`. It prints each layer's box for checking.
3. **Reference roles:** Assign each attached reference one role (identity, product truth, layout, material, light, style). Resolve conflicts: style cannot override an approved logo or product shape.
4. **Prompt:** Specify result, subject/action, composition, medium/style, visible details, and constraints. State reference roles explicitly. Read [prompt-blocks.md](references/prompt-blocks.md) when writing the prompt: style block, one item per image, background rule, and the check after generating.
5. **Attach:** Attach actual selected image files; file paths written in prompt text do not attach images. Attach a geometry sketch with a legend if needed for placement.
6. **Generate & compare:** Produce one candidate (or a small set). View candidates at target delivery size. Check required content, identity, geometry, crop, and file properties before choosing by taste. Reject variants altering protected references.
7. **Record:** Save exact prompt, tool and model name, reference roles, clean output files, and `layout.json`. Never present generated text as exact. When the user approves or praises a result, record what they liked with `taste add` ([taste and lessons](../image-verify/references/project-memory.md#taste-and-lessons)).
8. **Stop conditions:** Stop after planned candidates are compared; stop and ask if references conflict unresolved or no generator is available; stop on tool failure without silent retry.
9. **Handoff:** For single review, hand to [image-verify](../image-verify/SKILL.md) (read [candidate-audit.md](../image-verify/references/candidate-audit.md) only when auditing a create contract). For multi-round repair loops, continue in [image-loop](../image-loop/SKILL.md) (read [review-loop.md](../image-verify/references/review-loop.md) only when planning multi-candidate rounds).
