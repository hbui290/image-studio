---
name: image-repair
description: Correct a specific defect in an existing image with a local edit, approved references, controlled compositing, and preservation checks. Use when the composition is accepted but one part is wrong - a distorted face, a malformed prop, a person or object to remove, pets or characters that must match reference sheets, a logo to place on a surface. Hand results to image-verify before claiming success. For a whole image that is merely soft or small use image-enhance.
---

# Local image repair

This skill fixes one region of an accepted image and keeps every other pixel. Use a sibling skill instead when:

- The whole image is soft rather than one object wrong: [image-enhance](../image-enhance/SKILL.md) first; it tests upscalers and proves the gain at display size.
- The target or the defect is not yet clear: [image-inspect](../image-inspect/SKILL.md) finds it and numbers the objects.
- The image is new, or the whole image must be regenerated with automated review rounds: [image-loop](../image-loop/SKILL.md).
- The user still has to choose what to change: [image-edit-map](../image-edit-map/SKILL.md) plans the edit with a numbered map. This skill then executes the masked local fix, and the [image-verify](../image-verify/SKILL.md) audit proves the rest of the image is unchanged.

A full worked case, with before/after images and the rejected attempts, is the [tavern hero example](https://github.com/hbui290/image-studio/blob/main/examples/image-repair/tavern-hero-case.md) in the repository; a skills install does not include it.

Tools: ImageMagick 7 `magick` for crops, masks, and composites; an image generator that accepts a crop and reference images, when new pixels are needed. Optional segmenters, upscalers, and face models are not prerequisites; check an unfamiliar machine with [tool-readiness.md](references/tool-readiness.md).

## Steps

1. **Fix the target.** Start from an untouched clean source. Record the exact target, permitted change, protected neighbors, and required output. If the target is ambiguous, use the `A:#7` source-coordinate map from image-inspect before editing. Read [scene-contract.md](../image-inspect/references/scene-contract.md) when references conflict, objects overlap, or geometry depends on nearby structures.
2. **Choose the smallest operation** that solves the defect. Missing eyes, fused objects, broken joins, and false text need new pixels or manual retouch; an upscaler cannot supply them.
3. **Generate or draw the patch.** Give the editor a crop with context and approved identity or product references. Keep observations about the old source separate from the requested result. Branch from the accepted clean source rather than chaining rejected candidates. Read [repair-and-composite.md](references/repair-and-composite.md) for object IDs, masks, crop alignment, perspective, exact artwork, and the compositing recipe.
4. **Composite through a final mask.** Treat a model input mask as guidance. Accept only reviewed pixels through a separate final acceptance mask; protect required shapes inside that boundary with a second mask. Inspect seams, occlusion, contact, shadows, and neighboring subjects at 100% and at display size.
5. **Verify** with [image-verify](../image-verify/SKILL.md) before claiming success. For protected pixels or several rounds, write `contract.json` and `review.json` as described in [candidate-audit.md](../image-verify/references/candidate-audit.md), then run:
   ```bash
   python3 <skills>/image-verify/scripts/audit_candidate.py \
     --contract contract.json --source source.png --candidate review.png \
     --mask final-acceptance-mask.png --review review.json --out round-0
   ```
   It needs Python 3.9+ with Pillow: run it as `uv run --with pillow python3 <skills>/image-verify/scripts/audit_candidate.py ...`, or install Pillow once with `python3 -m pip install pillow` and use `python3` directly. `<skills>` is the folder that holds the skill folders. Read `decision.json` and follow [decisions.md](../image-verify/references/decisions.md).
6. **Repeat or stop.** Use at most three repair rounds and the stop rules in [decisions.md](../image-verify/references/decisions.md). When two candidates repeat the same failure, change the approach (crop, reference, mask, or a deterministic edit) instead of rewording the prompt.

## Outputs

- `review.png`: the uncompressed full-size composite; export WebP or JPEG only after it passes.
- The patch, the crop-local and full-size final acceptance masks, and the audit folder (`evidence.json`, `decision.json`) when the audit was run.
- An evidence ledger (sources, crop, candidate, mask, tool actually used, dimensions, rejected variants, reviews); its contents are listed at the end of the masked composite section in [repair-and-composite.md](references/repair-and-composite.md#masked-composite).
