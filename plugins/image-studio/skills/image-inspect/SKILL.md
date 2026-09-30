---
name: image-inspect
description: Diagnose a supplied image, locate named or repeated objects, and prepare a source-grounded edit contract without changing pixels. Use for critique, defect mapping, or unclear edit targets. Not for numbered edit planning (image-edit-map) or JSON style extraction (image-reverse-engineer).
---

# Image inspection

Inspect the actual clean image at native pixels and at its intended display size. Check layout, crop, CSS effects, export quality, and source resolution before attributing softness to image generation. Report visible defects and uncertainty; do not edit for an assessment-only request. Read [diagnosis.md](references/diagnosis.md) for the image contract and the defect-to-first-action table.

When the user points to one of several similar objects, assign stable IDs such as `A:#7` and record their locations against the **original clean image**, not the resized preview. If useful, record normalized top-left `[x, y, width, height]` boxes and separate arrow targets; mark measured versus estimated coordinates. Make a separate numbered review copy and matching legend only when that helps disambiguate the target. For a dense scene, map groups first and use close-ups with the same IDs. Retire an ID when its object is removed; never recycle it. Re-map after a changed source or crop. Keep the untouched source as the editing input; a bounding box is not a segmentation mask. Inspect connected structures through supports, openings, overlaps, and paths beyond the proposed crop.

For an edit handoff, distinguish observed source facts, inferred details, requested changes, protected properties, allowed physical consequences, and observable result checks. Give every reference a role and authority. Read [scene-contract.md](references/scene-contract.md) for multi-reference or spatially difficult scenes. Return the source version, dimensions, target IDs, reference roles, and unresolved unknowns. Do not claim hidden content, original layers, or an exact font from a flat image.
