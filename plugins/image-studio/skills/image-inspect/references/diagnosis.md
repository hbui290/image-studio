# Image contract and diagnosis

Use this before editing a supplied image, or when a new image must meet a delivery target. It records what the image is for, what must stay fixed, and the least disruptive fix for each defect.

## Establish the image contract

- Identify the image's purpose and delivery surface: hero, portrait, product image, thumbnail, illustration, background, print, game art, or another target. Record required dimensions, aspect ratio, format, transparency, file-size budget, and where it will be viewed.
- Identify the source of truth for each protected element: original image, approved character sheet, product photo, logo/vector, diagram data, or user-supplied reference. Record which items may change and which must remain fixed.
- For a multi-object or high-stakes edit, give each requested change and protected invariant a short ID with an observable pass condition. Mark file requirements separately from visual requirements. Decide before generation which failures would reject a candidate and which observations are advisory; an unknown required result is not a pass.
- Keep an untouched source. Save candidates as new files until accepted. Do not silently replace the lossless source or claim that an AI reconstruction is a lossless restoration.
- For a new image with no source to preserve, define subject, composition, style, and approved references; generate candidates using the selected tool's instructions and judge them against the image contract. Preservation masks apply when editing an existing image.
- When only an assessment is requested, inspect and report; edit only if the user requests a change.

## Diagnose at two scales

Inspect the source at native pixels **and** the rendered result at the target size. For a web image, check CSS crop/fit, overlays, blur filters, opacity, device pixel ratio, and responsive positions before editing pixels. For print, inspect the physical size and effective resolution. Use close crops to locate defects, then review the entire composition.

| Finding | First useful action |
| --- | --- |
| Wrong crop, contrast, or layout | Correct framing or presentation; preserve the image pixels if they are sound. |
| Compression blocks, noise, mild softness | Re-export from the user's original file if they have one; otherwise use [image-enhance](../../image-enhance/SKILL.md) and accept only a gain its display-size comparison confirms. |
| Too few pixels, or a large but visibly soft source | Use [image-enhance](../../image-enhance/SKILL.md): test a suitable super-resolution model on a representative crop. Resize every candidate back to the same delivery size before comparing; reject changes that only look sharper at 4× zoom, oversmooth line art, or invent details. |
| Missing eyes, broken geometry, fused objects, extra limbs, inconsistent texture | Use a small local edit, manual retouch, or compositing with an approved reference. Upscaling alone cannot solve missing semantics. |
| Damaged alpha edge or unwanted background | Repair the matte or background, then inspect the edge against light and dark surfaces. For a jagged, speckled, or outlined edge on a transparent PNG, use the [cutout edges](../../image-enhance/references/cutouts.md#cutout-edges) recipe in image-enhance. |
| Composition fundamentally wrong | Recompose or regenerate only when that larger change is within the user's request. |

Choose the least disruptive operation that solves the observed defect. Use specialist generation or editing tools according to their own instructions when pixels must be generated. Use deterministic image tools for cropping, masking, color correction, resizing, and export when those operations are sufficient.

For connected structures or crowded scenes, map supports, openings, overlaps, and repeated object instances before editing. Check structure and proposed masks against source pixels. Do not infer a proprietary editor's internal algorithm from an open-source example.

When a target is ambiguous among repeated objects, make a numbered review copy and a matching plain-language legend so the exact instance can be selected. Keep the clean source as the edit input, retain stable IDs across revisions, and store object locations in source-image coordinates. A rectangle locates an object; it is not an approved mask. Skip the map when the target is already unambiguous.

## When a generated result misses the request

Find the cause before rewriting the prompt:

| What went wrong | What to inspect | Next action |
| --- | --- | --- |
| An object is missing or duplicated | Count it across the whole image, background included | State the exact count and role; remove competing objects from the prompt |
| A property landed on the wrong object | Trace each color, garment, or material to its subject | Tie the property to a named part or reference ID |
| The layout is wrong | Large shapes, overlap, viewpoint, paths | Attach a sketch or state the spatial relation |
| A face, product, or outfit drifts | Distinctive features against the source | Attach the clean reference or a crop and limit its role |
| Text is wrong | Spelling, line breaks, duplicates, size | Leave the space empty and place the text as a layer ([image-create](../../image-create/SKILL.md) step 3) |
| The action reads backward | Pose, gaze, contact, direction | Name the decisive physical cues or attach a pose sketch |
| A local edit changed other regions | Protected details against the accepted source | Narrow the request, restart from the best source, and composite through a mask |
| A diagram looks right but is false | Every label, relation, and fact | Check against a real source; draw exact diagrams with deterministic tools |
| The file is unusable | Size, alpha, format, editability | Check the file and use the tool's output setting (for example `transparent_background`) |
| Correct but dull | Hierarchy, depth, scale, material contrast | Change one named artistic decision and keep what works |

