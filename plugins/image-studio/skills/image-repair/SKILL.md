---
name: image-repair
description: Correct a specific defect in an existing image with a local edit, approved references, controlled compositing, and preservation checks. Use when the composition is accepted but an object, face, structure, edge, or mark is wrong. Hand results to image-verify before claiming success.
---

# Local image repair

Start from an untouched clean source and identify the exact target, permitted change, protected neighbors, and required output. If the target is ambiguous, use a source-coordinate map before editing. Read [scene-contract.md](../image-inspect/references/scene-contract.md) when references conflict, objects overlap, or geometry depends on nearby structures.

Choose the smallest operation that solves the defect. Test super-resolution on a representative crop even when the source has many pixels but looks soft; compare at the same final display size and reject a model that only enlarges the blur. Missing eyes, fused objects, broken joins, and false text need new pixels or manual retouch. When generation is needed, give the editor a crop with context and approved identity or product references. Keep observations about the old source separate from the requested result. Branch from the accepted clean source rather than chaining rejected candidates.

Read [repair-and-composite.md](references/repair-and-composite.md) for object IDs, masks, crop alignment, perspective, exact artwork, and a compositing recipe. Treat a model input mask as guidance. Accept only reviewed pixels through a separate final mask; protect required shapes inside that boundary with a second mask, then inspect seams, occlusion, contact, shadows, and neighboring subjects. Use [tool-readiness.md](references/tool-readiness.md) on an unfamiliar machine; optional segmenters, upscalers, and face models are not prerequisites. Hand the candidate, source, mask, and change record to image verification before claiming success.
