# Designer review

Read by [image-verify](../SKILL.md) before showing a new or regenerated image to the user, and before delivery. It reviews the way a strict art director does: find problems first, everywhere in the image, not only in the region that was edited.

## 1. Make the review views

With [ImageMagick](https://imagemagick.org) 7:

```bash
magick in.png -crop 3x2@ +repage tile-%d.png                     # 6 tiles at 100% (over 3000 px a side: -crop 4x4@)
magick in.png -gravity North -crop x90+0+0 +repage edge-top.png    # 4 edge strips: cut objects hide here
magick in.png -gravity South -crop x90+0+0 +repage edge-bottom.png
magick in.png -gravity West -crop 90x+0+0 +repage edge-left.png
magick in.png -gravity East -crop 90x+0+0 +repage edge-right.png
magick in.png -colorspace Gray gray.png                            # value structure and focal point
magick in.png -resize 120x120 thumb.png                            # does it still read when small?
magick approved.png in.png -resize x600 +append lineup.png         # next to the last approved version
```

Open every view. Crop text, logos, faces, and hands again at 200% when the 100% tile is unclear. `lineup.png` needs an earlier approved file; skip it for a first draft.

## 2. What to look for

- **One artist, one style.** Outline weight is even; each object uses the same shading language (for flat art: 2-3 tones with hard shadow edges). Flag any patch whose rendering differs from the style block, such as a 3D-render or photo look inside painted art: glossy reflections, specular sparkles, unwanted bloom, real fabric or fur texture, fine mesh. Two drawing styles in one image is the most common reason an image looks "AI".
- **Soft or damaged areas.** Mushy detail, smeared texture, melted edges, or noise that the rest of the image does not have.
- **Logic and anatomy.** Hands and finger counts, repeated identical poses, objects that float or merge, impossible perspective.
- **Edges and seams.** Objects cut flat by the frame, halos or jagged edges around subjects, visible patch borders.
- **Color and light.** Colors outside the palette, light from the wrong side, the focal subject not the brightest area (check `gray.png`).
- **Readability.** At 120 px the subject and any title still read.
- **Against the approved version.** Nothing that was approved changed unless the user asked for it.

## 3. Report

Write the problems before any opinion, in a table, and do not praise:

| No. | Region | Problem | Severity (high / medium / low) | Fix |
|---|---|---|---|---|

Fix high and medium problems before showing the image; list low ones for the user. In image-loop, mark each problem `fail` on the brief check it breaks and never invent a check ID; a problem no check covers goes to the user, not into an extra round. When a fix needs a new generation, edit only the numbered problems and keep everything else (see the region-edit prompt in [repair-and-composite](../../image-repair/references/repair-and-composite.md#prompt-structure)). A self-review is not independent: say so, and use [independent review](independent-review.md) when it is available.
