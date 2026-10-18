# Repair rules

Use these gates only for exact logos, packaging text, and transparent exports. These are visual acceptance rules, not guarantees from prompts or exit codes.

## Source and clean plate

1. Keep one approved source file per mark; branch from it, not rejected candidates. If detail degrades, restart from approved source with tighter crops, masks, or references; never search for or paste other artwork unless user supplied it. Fix named regions only.
2. From a repo checkout, see `examples/image-repair/logo-brief.json` for a per-occurrence brand repair brief.
3. Inspect clean plate before placing a logo: no old lettering, stars, shadows, outlines, or rules. Reject plates with rectangles, repeated textures, stretched rows, banding, or damaged folds. Never hide an old mark under a larger new one.

## Per-occurrence logo checks

1. Inventory occurrences by source coordinates, using the same approved source file. Disclose raster reconstruction uncertainty.
2. Extract mark with real alpha; test over light/dark backdrops. Ensure saturation did not leak into mask and interior symbols remain. Never paste rectangular backgrounds.
3. Measure placement; apply perspective once. Preserve silhouette, seam geometry, lighting, occlusion, letter proportions, and pixels outside accepted masks.
4. Inspect occurrences at native size and delivery size, and at 200% when the native view is unclear. Reject doubled strokes, residual ink, missing symbols, unreadable marks, matte boxes, or bright fringes.

## Alpha and composite safeguards

- Build grayscale masks with alpha disabled before conversion or arithmetic; opaque white must identify intended changed pixels.
- Reset geometry, offsets, modes, and channels explicitly, or use full overlays. Inspect final flattened files.
- Cutouts: verify empty areas are transparent and points in retained rails/bodies stay opaque over light and dark backdrops. Corner alpha zero alone can pass an almost invisible frame.

## Repair history for multi-chat repairs

Keep this record beside round folders when repairs span turns or chats, or when a missed defect is reported. With a `.image-studio/` store ([project memory](../../image-verify/references/project-memory.md)), use `D<n>` IDs from `defects.jsonl` (`defect add` / `defect close`); record narrative here. Start from frozen source. If two rounds repeat the same failure, follow [`stop_repeated_failure`](../../image-verify/references/decisions.md).

For object removal, record separate checks for the recognizable face/silhouette and its residue: frame edges and corners, straight border strokes, glow or color spill, shadows, and fragments visible at occlusion boundaries. A prior pass that checked only for a recognizable whole object is insufficient; add a new stable defect/check for anything later found and inspect it at 100% and 200% before closing it.

### Entry template

```text
## YYYY-MM-DD — round N
- Frozen source: <path>; SHA-256: <hash>
- Defects: <stable IDs (store D<n>) and source bounds>
- Protected: <shapes, text, objects, pixels>
- Attempt: <tool and candidate path>
- Review: <verdict per ID, crop/audit evidence>
- Rejected because: <visible failure, or none>
- Next method: <changed method, or resolved>
- Final artifact: <path/hash, native + delivery-size result>
```

Before delivery, decode and inspect final ZIP files: check dimensions, color, alpha, logo occurrences, copy, and outside-mask preservation. Report failed or uncertain checks explicitly.
