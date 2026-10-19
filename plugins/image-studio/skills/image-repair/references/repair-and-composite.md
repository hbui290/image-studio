# Local repair and compositing reference

Read this when an image needs a generative patch, removal, outpaint, or controlled replacement. Adapt geometry and tools to the input; sample dimensions are illustrative. For portraits, products, architecture, cutouts, text and logos, marks on surfaces, or web heroes, also read [subject-checks.md](subject-checks.md).

## Control generated edits

- Supply the context crop and approved references with declared roles. Specify the exact change, protected subjects, count, pose, perspective, and layout.
- Branch from the approved source rather than feeding each generated output into the next edit. A prompt alone cannot protect pixels outside the requested change.
- Use a crop with context for lighting and geometry; accept only reviewed pixels through a final acceptance mask. Check polarity, full object coverage, alignment, feathered edges, and seams.
- For rebuilding an object's interior, use nested masks: an outer acceptance boundary and inner protection for silhouettes, line work, or exact details. Inspect protected islands and new pixels for doubled edges.
- Treat novel details as proposed art, not recovered facts. If reference material cannot establish an identity-critical feature, report the uncertainty instead of inventing details.

## Before the edit

Record:
- Source image and protected reference images.
- Full image dimensions and target delivery dimensions.
- Crop rectangle `(x, y, width, height)` in **source-image pixels**.
- Allowed change and protected subjects or regions.
- Baseline full image and defect close-up at 100%.

Choose a crop slightly larger than the defect so the generator sees lighting, texture, and perspective. If the source dimensions change, recalculate crops and masks.
For connected structures, trace supports, attachment points, repeated parts, and clear openings beyond the crop before generating pixels.

## Selecting one object in a crowded image

Before editing repeated objects, record a map with `ID`, label, source-pixel box or crop, neighbors to protect, and edit status. Use stable IDs (`A:#3`). Preview masks at native pixels before accepting; verify holes, thin parts, shadows, overlaps, and adjacent hands or faces.
Manual selection suffices for clear objects. Optional segmenters ([SAM 3](https://github.com/facebookresearch/sam3), rembg `sam`) propose masks; verify their runtime and sample inference before relying on them, or draw masks manually.
For tiny objects in high-resolution scenes, crop around the target at source resolution before requesting masks. In overlapping tiles, convert tile-local coordinates back to source pixels `(tile_x + u, tile_y + v)`.

## Prompt structure

Attach actual reference files and use the appropriate form:

```text
Image 1 is the source crop and fixes layout, camera angle, pose, and lighting.
Image 2 is the approved reference for [identity/material/shape], if supplied.
Change only [specific damaged object or region] by [specific correction].
Keep [subjects, count, geometry, text, branding, and nearby details] unchanged.
Match [medium, line quality or grain, perspective, light direction, palette].
Do not add [objects or content that would violate the brief].
```

For several defects in one image, number them and describe each subject by position, so the editor changes only those:

```text
Edit this image. Keep the composition, characters, costumes, colors, lighting and background exactly as they are.
Change only these N things:
1. <region by position, e.g. "the hand of the woman on the left">: <what is wrong> -> <the correct result>.
2. ...
Do not change the faces, <other protected details>, or the color palette. Same aspect ratio, highest resolution available.
```

If the editor changes too much, fix one region per turn: `Edit only <region by position>. <correct result>. Change nothing else - not the face, the hair, or the background.` Generators often redraw the whole image instead of the region, so always composite through the acceptance mask and compare faces and colors with the source before accepting.

For removal, describe what should appear behind the removed object (texture fill for periodic patterns, reference-guided generation for new content; see [LaMa](https://github.com/advimman/lama) for inpainting). For outpainting, identify edges to extend and objects not to duplicate. For face repair, canonical character references control identity. Avoid vague requests such as "make it 4K".

## Masked composite

Confirm the generated candidate matches the crop's aspect ratio and landmarks before resizing. In a POSIX shell with ImageMagick:

```bash
src='input.png'
candidate='generated-patch.png'
mask='patch-mask.png'
x=1200
y=400
w=600
h=500

magick "$src" -crop "${w}x${h}+${x}+${y}" +repage crop.png
magick "$candidate" -resize "${w}x${h}!" candidate-sized.png

# Acceptance mask in crop coordinates: white polygon accepted, black kept, edge softened inward only.
magick -size "${w}x${h}" xc:black -fill white \
  -draw 'polygon 120,80 480,70 520,420 90,430' \
  -blur 0x3 -level 50%,100% "$mask"

magick candidate-sized.png "$mask" \
  -alpha off -compose CopyOpacity -composite patch-with-alpha.png

magick "$src" patch-with-alpha.png \
  -geometry "+${x}+${y}" -compose Over -composite review.png

# Prove nothing outside the mask changed: protect.png is white wherever the mask is 0.
magick -size "$(magick identify -format '%wx%h' "$src")" xc:black "$mask" -geometry "+${x}+${y}" \
  -compose Over -composite -threshold 0 -negate protect.png
magick compare -metric PDC -read-mask protect.png "$src" review.png null:   # must print 0; exit 1 if any pixel differs
```

Create `patch-mask.png` at exactly `w × h`: white accepts new pixels, black keeps the source. Feather only the boundary, and only inward: a grown or blurred-outward mask spreads past the polygon and can reach the crop edge, which shows as a rectangular seam. If the mask must grow, check that `magick "$mask" -format '%@' info:` stays clear of the crop edges.
- **Polarity:** The final acceptance mask uses white for accepted pixels and black for kept pixels. For tools requiring inverted alpha (such as OpenAI edits where transparent pixels mark areas to redraw), convert with `magick crop.png \( "$mask" -negate \) -alpha off -compose CopyOpacity -composite openai-mask.png`, keeping the original as the acceptance mask.
- **Coverage:** Include complete silhouettes with a small margin. If a mask cuts through an object, regenerate or redraw rather than hiding mismatches with wide blur.
- **Nested masks:** For interior repairs, subtract protected interior masks (emblems, line work) from the outer acceptance mask before compositing.
- **Bit depth:** Keep the source's depth. Do not add `-depth 8` to a 16-bit source (`magick identify -format '%z' input.png` prints 16): it changes many pixels outside the edit. The `compare -metric PDC` check above works at 16 bits; the pixel audit refuses 16-bit color PNGs, so for it compare 8-bit copies of both files (`magick input.png -depth 8 input-8.png`, same for `review.png`) and deliver the 16-bit file. On Windows PowerShell, use equivalent variables (`$crop = "$($w)x$($h)+$x+$y"`) with the same white-accepts convention.

Inspect `review.png` before lossy export. For exact preservation outside edits, place the crop-local mask on a full-size black canvas at `(x, y)`, invert the nonzero mask footprint to obtain the protected area, and verify zero changed pixels there (the `compare -metric PDC -read-mask` command above; `PDC` counts changed pixels, while `AE` on ImageMagick 7.1.2 does not give a pixel count for color images). Inspect seams at 100% and delivery size. If colors differ, convert profiles into a common colorspace before blending rather than relabeling metadata ([ImageMagick color management](https://imagemagick.org/color-management/)).

Record an evidence ledger: source and approved references; crop, candidate, and accepted mask; tool/model invoked; dimensions before/after; rejected variants and why; 100% review and final display review.

## Bent rigid objects

A sword, spear, staff, or gun that bends where a hand holds it is the most repeated generator error with props. Measure it, then repaint only the short part:

```bash
python3 <skills>/image-verify/scripts/studio_state.py axis-check --image hero.png \
  --points 25,355 230,540 850,1570 --guide guide.png     # pommel, crossguard, tip; exit 1 above 3 degrees
```

It prints each segment's angle, the bend, and where every point belongs on the longest segment's line, and draws that line in `guide.png`. Keep the longest straight part (usually the blade); mask the grip, pommel, and the hand around them; attach `guide.png` as the geometry reference ("the grip and pommel lie exactly on the red line, the fist closes around the grip on it"); composite through the mask; run `axis-check` again on the result.

