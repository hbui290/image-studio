---
name: image-repair
description: Correct a specific defect in an existing image with a local edit, approved references, controlled compositing, and preservation checks. Use when the composition is accepted but one part is wrong - a distorted face, a malformed prop, a person or object to remove, pets or characters that must match reference sheets, a logo to place on a surface. Hand results to image-verify before claiming success. For a whole image that is merely soft or small use image-enhance.
---

# Local image repair

Start from an untouched clean source and identify the exact target, permitted change, protected neighbors, and required output. If the target is ambiguous, use a source-coordinate map before editing. Read [scene-contract.md](../image-inspect/references/scene-contract.md) when references conflict, objects overlap, or geometry depends on nearby structures.

Choose the smallest operation that solves the defect. If the whole image is soft rather than one object wrong, use [image-enhance](../image-enhance/SKILL.md) first; it tests upscalers and proves the gain at display size. Missing eyes, fused objects, broken joins, and false text need new pixels or manual retouch. When generation is needed, give the editor a crop with context and approved identity or product references. Keep observations about the old source separate from the requested result. Branch from the accepted clean source rather than chaining rejected candidates.

Read [repair-and-composite.md](references/repair-and-composite.md) for object IDs, masks, crop alignment, perspective, exact artwork, and a compositing recipe. Treat a model input mask as guidance. Accept only reviewed pixels through a separate final mask; protect required shapes inside that boundary with a second mask, then inspect seams, occlusion, contact, shadows, and neighboring subjects. Use [tool-readiness.md](references/tool-readiness.md) on an unfamiliar machine; optional segmenters, upscalers, and face models are not prerequisites. Hand the candidate, source, mask, and change record to image verification before claiming success. Use at most three repair rounds and the stop rules in [decisions.md](../image-verify/references/decisions.md). For new images or whole-image edits that need automated review rounds, use `image-loop` instead; this skill is for one region of an accepted image.
