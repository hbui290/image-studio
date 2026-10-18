---
name: image-repair
description: "Fix one region, correct defect, distorted face, malformed prop, remove object, place logo: repair a local area of an accepted image using context crop, host generation, compositing through an acceptance mask, and preservation checks."
---

# Local image repair

Fix one region of an accepted image while keeping other pixels untouched.

Routing: For whole-image softness use [image-enhance](../image-enhance/SKILL.md); to locate defects use [image-inspect](../image-inspect/SKILL.md); for full-image generation/loops use [image-loop](../image-loop/SKILL.md); to plan edits use [image-edit-map](../image-edit-map/SKILL.md).

Run scripts; do not read their source - use `--help` for usage.

## Operational checklist

0. **Memory:** If not in context, run `python3 <skills>/image-verify/scripts/studio_state.py brief` (see [using the store in a skill](../image-verify/references/project-memory.md#using-the-store-in-a-skill)).
1. **Target:** Fix one region from an untouched source. Read [preflight.md](references/preflight.md) only before the first repair on a machine or in a new chat. Read [repair-rules.md](references/repair-rules.md) only when editing logos, packaging text, transparent exports, or logging multi-chat repairs.
2. **Generate patch:** Generate the patch with the host image generator (Codex: `image_gen.imagegen` with `prompt`, `referenced_image_paths` = context crop + approved refs, `transparent_background` for cutouts; it takes no size, so resize with [ImageMagick](https://imagemagick.org) `magick` before compositing. Claude Code has no built-in generator: without one, stop and return the prompt). Do not search the disk for replacement artwork. Composite existing pixels only from a file the user supplied or an approved reference or logo in `brand show`. Read [repair-and-composite.md](references/repair-and-composite.md) only when configuring crops or masks.
3. **Composite:** Composite through a final acceptance mask. For object removal, check frame edges and corners, straight border strokes, glow or color spill, shadows, and occlusion at 100%, and at 200% only when the 100% view is unclear; "no recognizable silhouette" is not enough if fragments remain.
4. **Verify:** Hand to [image-verify](../image-verify/SKILL.md). Read [candidate-audit.md](../image-verify/references/candidate-audit.md) only when running an automated candidate audit.
5. **Repeat or stop:** At most three repairs after the first candidate; when the same checks fail twice in a row ([`stop_repeated_failure`](../image-verify/references/decisions.md)), change the method. When a new method works after two failures, record it with `lesson add ... --worked` ([taste and lessons](../image-verify/references/project-memory.md#taste-and-lessons)).
6. **Gate before claiming done:** With a project store, run `gate --deliverable` once before saying done ([using the store in a skill](../image-verify/references/project-memory.md#using-the-store-in-a-skill)).
