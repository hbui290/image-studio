# Scene and reference contract

Use this when a repair has several references, repeated targets, occlusion, difficult geometry, or a later agent must continue it. A clear one-object edit can use an ordinary comment or region selection plus the main skill's checks. This contract can be a short table or notes; JSON and a dedicated mapping application are optional. When an audit needs JSON, write the `contract.json` in [candidate-audit.md](../../image-verify/references/candidate-audit.md): it uses the same `A:#7` IDs with `[x, y, width, height]` boxes in source pixels.

## Separate evidence, decisions, and checks

Keep three records so the old appearance does not leak into the requested result:

| Record | What belongs here | Example |
| --- | --- | --- |
| Clean-source observations | Visible objects, source dimensions, measured or estimated bounds, materials, text, overlaps, and confidence | `A:#7 mug has a broken-looking handle; the knight's fingers cross its left edge` |
| Edit decisions | Target ID, property and requested change, protected properties, allowed physical consequences | `Repair A:#7 handle; keep the knight's hand; allow a local contact shadow on the mug` |
| Result checks | Required outcome, protected invariants, objective file checks, optional preferences | `One continuous handle; no extra fingers; source pixels outside the acceptance mask remain unchanged` |

Mark each observation `visible`, `inferred`, or `unknown`. A flat image cannot establish an object's hidden back, original layers, exact font, or missing facial details. Keep source observations unchanged when the user revises a target; revise the edit decision and its affected result checks instead. Do not weaken a check just because a candidate failed it.

## Assign source and reference authority

For each input, note its ID, path or stable version, role, allowed influence, and exclusions. Typical roles are **clean target**, **identity or product truth**, **layout**, **material**, **lighting**, and **style**. An approved logo or product drawing controls exact geometry; a mood image can guide style but cannot override that geometry. A reference for clothing does not automatically control pose. If two references give conflicting instructions for the same property, resolve the authority before generation.

Attach the actual selected files to the image tool in the stated order. A filename written in the prompt does not supply pixels. For a crowded image, make a separate annotated review copy with stable IDs and a plain-language legend. Keep its badges out of the clean source used for editing. Record locations in clean-source coordinates and the display transform separately; never apply screenshot coordinates to a differently scaled source. A box only locates a target. Inspect or draw an actual mask before pixel replacement.

## Map spatial dependencies

For each repaired element, trace what supports it, touches it, overlaps it, casts a shadow on it, or must remain visible behind it. List the front-to-back order and any open path or joint that must connect across the crop boundary. A railing, stair, cloak, bottle handle, or plant cannot be judged only from its isolated silhouette. If an object moves or changes material, note legitimate local consequences such as shadow, reflection, fold, or contact point. Keep those consequences inside the agreed change area or expand it transparently when necessary.

When a requested target is absent or its identity is uncertain, inspect the source and user reference again before generating. Do not let a model invent the missing object and then report it as repaired. For an unseen side or occluded detail, use an approved multi-view reference where available; otherwise mark the proposed detail as an inference.

## Compile only the current edit

Build a concise instruction from the clean source, target ID and description, requested delta, permitted consequences, protected properties, reference roles, and observable checks. Resolve IDs to words and coordinates; a generator cannot infer what `A:#7` means from the ID alone. Do not feed it a full inventory full of obsolete target descriptions. For example, if the source record says a cloak is blue and the user asks for green, keep `blue` in the source record but instruct the generator to make the cloak green while preserving its folds and attachment points.

Before submission, inspect the instruction for contradictions: old color versus requested color, `keep everything unchanged` versus a moved object and its shadow, or a style reference that would replace a protected face. If layout or pose is difficult, a simple sketch with source-matched aspect ratio can specify silhouettes and overlap; label construction marks so they do not appear in the final art. Review geometry before surface detail.

This contract adapts the source-versus-selection separation in [image-reconstruction](../../image-reconstruction/SKILL.md) and reference authority in [Visual Design Kit](https://github.com/newmindsgroup/visual-design-kit/blob/main/plugins/visual-design-studio/library/draft-skills/design-media-reference-control/SKILL.md). Those projects are research sources, not required installations.
