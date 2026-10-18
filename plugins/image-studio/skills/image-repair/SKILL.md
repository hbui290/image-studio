---
name: image-repair
description: "Fix one region, correct defect, distorted face, malformed prop, remove object, place logo: repair a local area of an accepted image using context crop, host generation, compositing through an acceptance mask, and preservation checks."
---

# Local image repair

Fix one region of an accepted image while keeping other pixels untouched.

Routing: For whole-image softness use [image-enhance](../image-enhance/SKILL.md); to locate defects use [image-inspect](../image-inspect/SKILL.md); for full-image generation/loops use [image-loop](../image-loop/SKILL.md); to plan edits use [image-edit-map](../image-edit-map/SKILL.md).

Run scripts; do not read their source - use `--help` for usage.

## Operational checklist

0. **Memory:** If not in context, run `studio_state.py brief` (see [using the store in a skill](../image-verify/references/project-memory.md#using-the-store-in-a-skill)).
1. **Target:** Fix one region from an untouched source. Read [Quick preflight](references/tool-readiness.md#quick-preflight) only when checking tool readiness. Read [repair-rules.md](references/repair-rules.md) only when editing logos, packaging text, transparent exports, or logging multi-chat repairs.
2. **Generate patch:** Generate the patch with the host image generator (Codex: `image_gen.imagegen` with `prompt`, `referenced_image_paths` = context crop + approved refs, `transparent_background` for cutouts; it takes no size, so resize with `magick` before compositing. Claude Code has no built-in generator: without one, stop and return the prompt). Do not search the disk for replacement artwork - composite existing pixels only from a file the user supplied or for an exact logo/brand mark. Read [repair-and-composite.md](references/repair-and-composite.md) only when configuring crops or masks.
3. **Composite:** Composite through a final acceptance mask. For object removal, check frame edges and corners, straight border strokes, glow or color spill, shadows, and occlusion at 100% and 200%; "no recognizable silhouette" is not enough if fragments remain.
4. **Verify:** Hand to [image-verify](../image-verify/SKILL.md). Read [candidate-audit.md](../image-verify/references/candidate-audit.md) only when running an automated candidate audit.
5. **Repeat or stop:** At most three rounds, change method after two repeated failures (link [`stop_repeated_failure`](../image-verify/references/decisions.md)).
6. **Gate before claiming done:** With a project store run the gate once before saying done (link `gate --deliverable` in [using the store in a skill](../image-verify/references/project-memory.md#using-the-store-in-a-skill)).
