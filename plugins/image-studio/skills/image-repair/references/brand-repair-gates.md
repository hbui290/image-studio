# Brand repair gates

Use these gates only for exact logos, text on packaging, and transparent exports. These are visual acceptance requirements, not guarantees provided by a prompt or a successful script exit.

## Freeze the source

1. Record one approved full-size source and one approved master for each logo or brand mark. Record which reference controls shape, color, material, and placement separately. A color request does not authorize replacing the product silhouette or ornament.
2. Keep rejected candidates separate. Branch each attempt from the approved source, not the latest generated image. If repeated regeneration has degraded detail, restart from the approved image and regenerate with a tighter crop, mask, or reference; do not search for or paste other existing artwork unless the user supplied it.
3. Fix the named region only. Do not regenerate the poster to move a logo, recolor foil, or remove one card. When a new composition is explicitly requested, treat it as a new draft and recheck all protected criteria.

## Replace a logo without double printing

From a repo checkout, see the [logo brief example](https://github.com/hbui290/image-studio/blob/main/examples/image-repair/logo-brief.json) in `examples/image-repair/logo-brief.json` for a per-occurrence brand repair brief covering pack and card placements.

1. Inventory every occurrence by source coordinates, including small logos on distant cards and packaging. Use the same approved master at each occurrence. If only a raster reference exists, disclose reconstruction uncertainty rather than claiming an exact vector recovery.
2. Make and inspect a clean plate **before** placing the new logo. It must contain no old lettering, tiny stars, shadows, outlines, or rules. Reject a plate with an obvious rectangle, repeated texture, stretched rows, banding, or damaged folds. Do not hide the old mark under a larger new one.
3. Extract only the mark with real alpha. Composite it over both light and dark backgrounds before use. Check that background saturation did not leak into the mask and that extraction preserved small dark interior symbols. Never paste the rectangular reference background.
4. Measure placement on the surface and apply perspective once. Keep silhouette, seam geometry, local lighting, occlusion, and recognizable letter proportions. Preserve existing text and material outside the accepted mask.
5. Inspect each occurrence at native size, 200% for diagnosis, and actual delivery size. Reject doubled strokes, residual old ink, missing symbols, unreadable small marks, hard matte boxes, bright fringes, or a logo hidden by the background. A clean header does not establish that the pack logo passed.

## Alpha and composite safeguards

- Build grayscale masks with alpha disabled before grayscale conversion, thresholding, negation, or mask arithmetic. Inspect the mask itself: opaque white must identify the intended changed pixels, not an entire band caused by inherited alpha.
- Treat geometry, page offsets, compose modes, and channel selections as stateful. Reset them explicitly or prepare a full-size overlay with known offsets. Inspect the final flattened file after the last command, not only intermediate crops.
- For cutouts, verify **both** sides: the intended empty region is transparent and representative points in every retained rail/body remain opaque. Corner alpha zero alone can pass an almost invisible frame.
- Review all four corners over light and dark backdrops. Do not shrink away the metallic outline to hide a fringe. Compare RGB and alpha separately when the task changes only transparency.

## Stop and handoff

When two consecutive reviews fail for the same reason, follow the [`stop_repeated_failure`](../../image-verify/references/decisions.md) rule: inspect the source, matte polarity, coordinate system, and old-mark removal.

Before delivery, review the exact final artifact and decode the files extracted from the final ZIP. Check dimensions, color, alpha, every logo occurrence, all copy, local seams, and outside-mask preservation as required by the contract. File integrity and metadata removal do not prove visual correctness. Metadata cleaning does not guarantee that image-generation detection is impossible; report only the specific metadata inspected or removed, without exposing private values.

Report failed or uncertain requirements explicitly. Do not call a draft final because the archive opens or a pixel audit passed.
