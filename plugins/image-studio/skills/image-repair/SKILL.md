---
name: image-repair
description: Correct a specific defect in an existing image with a local edit, approved references, controlled compositing, and preservation checks. Use when the composition is accepted but one part is wrong - a distorted face, a malformed prop, a person or object to remove, pets or characters that must match reference sheets, a logo to place on a surface. Hand results to image-verify before claiming success. For a whole image that is merely soft or small use image-enhance.
---

# Local image repair

This skill fixes one region of an accepted image and keeps every other pixel. Use a sibling skill instead when:

- The whole image is soft rather than one object wrong: [image-enhance](../image-enhance/SKILL.md) first; it tests upscalers and proves the gain at display size.
- A transparent cutout has jagged or haloed edges: try the [cutout edges](../image-enhance/references/recipes.md#cutout-edges) recipe in image-enhance first; regenerate the edge here only when shrinking it is not enough, with the two-pass prompts that recipe gives.
- The target or the defect is not yet clear: [image-inspect](../image-inspect/SKILL.md) finds it and numbers the objects.
- The image is new, or the whole image must be regenerated with automated review rounds: [image-loop](../image-loop/SKILL.md).
- The user still has to choose what to change: [image-edit-map](../image-edit-map/SKILL.md) plans the edit with a numbered map. This skill then executes the masked local fix, and the [image-verify](../image-verify/SKILL.md) audit proves the rest of the image is unchanged.

A full worked case, with before/after images and the rejected attempts, is the [tavern hero example](https://github.com/hbui290/image-studio/blob/main/examples/image-repair/tavern-hero-case.md) in the repository; a skills install does not include it.

Tools: [ImageMagick 7](https://imagemagick.org) `magick` for crops, masks, and composites; an image generator that accepts a crop and reference images, when new pixels are needed. Optional segmenters, upscalers, and face models are not prerequisites; check an unfamiliar machine with [tool-readiness.md](references/tool-readiness.md).

## Steps

For exact logos, text on packaging, or transparent exports, apply [brand repair gates](references/brand-repair-gates.md) before the steps below. These gates require a clean plate, per-occurrence logo review, and checks of the exact final exported artifact.

0. **Load project memory.** If not already in context, run `studio_state.py brief`; see [using the store in a skill](../image-verify/references/project-memory.md#using-the-store-in-a-skill) to load memory or create a store.
1. **Fix the target.** Start from an untouched clean source. Record the exact target, permitted change, protected neighbors, and required output. If the target is ambiguous, use the `A:#7` source-coordinate map from image-inspect before editing. Read [scene-contract.md](../image-inspect/references/scene-contract.md) when references conflict, objects overlap, or geometry depends on nearby structures.
   For a repeated edit, an earlier correction, or a user-reported miss, read and update the task's [repair history](references/repair-history.md) before making another candidate. Keep stable defect IDs (with a store, the `D<n>` IDs from step 0; status lives in `defects.jsonl`) and write down the evidence, rejected approach, and next materially different method so the next turn can inherit it.
2. **Choose the smallest operation** that solves the defect. Missing eyes, fused objects, broken joins, and false text need new pixels or manual retouch; an upscaler cannot supply them.
3. **Generate or draw the patch.** In Codex the patch comes from `image_gen.imagegen` (args: `prompt`, `referenced_image_paths` = the context crop plus approved references); in Claude Code from whatever image generator the host provides. Then composite it through the final acceptance mask (step 4). Keep observations about the old source separate from the requested result. Do not search the disk for replacement artwork or reuse other existing images as patch material; composite existing pixels only from a file the user supplied for this job or for an exact logo / brand mark / packaging text. Branch from the accepted clean source rather than chaining rejected candidates. Read [repair-and-composite.md](references/repair-and-composite.md) for object IDs, masks, crop alignment, perspective, exact artwork, and the compositing recipe.
4. **Composite through a final mask.** Treat a model input mask as guidance. Accept only reviewed pixels through a separate final acceptance mask; protect required shapes inside that boundary with a second mask. Inspect seams, occlusion, contact, shadows, and neighboring subjects at 100% and at display size.
   For object removal, run a residual sweep before passing: check the face, every frame edge and corner, straight border fragments, glow or color spill, shadows, and slivers exposed around occlusion. “No recognizable silhouette” is not enough when any object-specific fragment remains; the gate's defect crops serve as the 100%, plus 200% when unclear, inspection (no separate extra crops), while checking that foreground contours stay continuous.
5. **Verify** with [image-verify](../image-verify/SKILL.md) before claiming success. For protected pixels or several rounds, write `contract.json` and `review.json` as described in [candidate-audit.md](../image-verify/references/candidate-audit.md), then run:
   ```bash
   python3 <skills>/image-verify/scripts/audit_candidate.py \
     --contract contract.json --source source.png --candidate review.png \
     --mask final-acceptance-mask.png --review review.json --out round-0
   ```
   It needs Python 3.9+ with Pillow: run it as `uv run --with pillow python3 <skills>/image-verify/scripts/audit_candidate.py ...` ([uv](https://docs.astral.sh/uv/)), or install Pillow once with `python3 -m pip install pillow` and use `python3` directly. `<skills>` is the folder that holds the skill folders. Read `decision.json` and follow [decisions.md](../image-verify/references/decisions.md).
6. **Repeat or stop.** Use at most three repair rounds; when two candidates repeat the same failure, follow the [`stop_repeated_failure`](../image-verify/references/decisions.md) rule. Append the review outcome and the next method to [repair history](references/repair-history.md) before continuing.
7. **Gate before claiming done.** In a project with a store, run `gate --deliverable` once before telling the user the deliverable is done; follow [using the store in a skill](../image-verify/references/project-memory.md#using-the-store-in-a-skill).

## Outputs

- `review.png`: the uncompressed full-size composite; export WebP or JPEG only after it passes.
- The patch, the crop-local and full-size final acceptance masks, and the audit folder (`evidence.json`, `decision.json`) when the audit was run.
- An evidence ledger (sources, crop, candidate, mask, tool actually used, dimensions, rejected variants, reviews); its contents are listed at the end of the masked composite section in [repair-and-composite.md](references/repair-and-composite.md#masked-composite).
