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

Confirm the generated candidate matches the crop's aspect ratio and landmarks before resizing. Resize keeping aspect (`magick patch.png -resize "${w}x${h}" ...`, no `!`); if the aspect differs, crop or pad the patch to the crop's aspect first. Never force-stretch a patch: a stretched patch misaligns every edge it continues. Then look before compositing: `studio_state.py align-check --base input.png --patch patch.png --at X,Y --mask mask.png --out-dir align` writes `align/checker.png` (base and patch in alternating squares: lines that jump at square borders are misaligned) and `align/overlay.png` (50/50 mix: doubled edges are misaligned). Without `--at` it scales the patch into the mask box (or the whole base) for the preview and exits 2 when their aspects differ by more than 1%. It also writes `align/align.json` (`base_sha256`, `patch_sha256`, `mask_sha256` or null, `at`, `accepted: false`). Open `checker.png` and `overlay.png` first; when nothing jumps or ghosts, rerun the same command with `--accept`: it re-hashes the inputs and sets `accepted: true` (exit 2 when the files changed since the views were written, the views are missing, or the patch was scaled for the preview: resize it and run align-check again).

When the patch position is unknown, `align-check --auto` finds it (needs numpy and OpenCV; without them it exits 2 with the install line in [image-verify](../../image-verify/SKILL.md#optional-numpy-and-opencv)): it matches the patch against the base with OpenCV template matching (TM_CCOEFF_NORMED) over patch scales 0.90 to 1.10, using only the patch's context outside `--mask` when one is given, prints `Auto: best match at X,Y, scale S, score V`, and then writes the same views and `align.json` as `--at X,Y`, so `--accept` (with `--auto` again, or with `--at X,Y`) and `blend --at X,Y --align ...` use that position. It exits 1 and writes nothing when the score is under 0.8, another place scores within 0.01 (a repeated motif), or the patch or its context outside the mask is flat (under 2 levels of variation, so it would match anywhere): "no reliable match", give `--at`; and when the best scale is more than 1% from 1: "the patch must be resized" to the printed size (it never resizes for you).

To get a mask from an edit, `studio_state.py mask-from-diff --before input.png --after edited.png --out mask.png [--threshold 24] [--grow 5] [--min-area 16]` marks pixels where a channel changed by more than the threshold, drops changed specks under `--min-area` pixels (8-connected, the same mask on both engines), grows the rest by `--grow` px, and writes an 8-bit gray PNG of 0 and 255 for `blend --mask` or `edit-check --mask`. It refuses to overwrite either input and exits 1 without a file when nothing changed. Check the mask against the intended region before blending: a generator that redrew the whole image changes pixels everywhere.

The short path, once the patch is resized to its crop and accepted: `studio_state.py blend --base input.png --patch patch.png --at X,Y --mask mask.png --align align/align.json --out candidate.png`. blend exits 2 before writing anything unless the record is accepted and its hashes and `at` match these inputs (align-check run without `--mask` writes a null `mask_sha256`, and blend then accepts any mask; the record stops accidental skips and is not a security boundary, since a hand-edited `align.json` is trusted); `--no-align-check` skips the check and prints "warning: registration not checked", for a patch that cannot be misplaced. The mask is at full image size: pixels at 128 or brighter take the patch, transparent mask pixels (alpha, or a palette/RGB transparent color) never do, and the feather softens only the band outside them; a transparent base keeps its alpha; 16-bit files are refused. It shifts the patch's color to match the ring of pixels around the mask and feathers the edge (default 3% of the mask box short side, 2 to 8 px; a `--feather` you pass warns above 5%). It prints the ring CIEDE2000 between patch and base (mean and p95; exit 1 "color mismatch" above 2.0 or 3.5, output still written; report only with `--no-match`), `seam_step` (mean |dL*| across the mask edge, next to the base's own value), and the changed area. Check it with `edit-check --before input.png --after candidate.png --mask mask.png --edge <feather>`: fewer than max(4, 0.5% of the mask) changed pixels fails as no effect or inverted (16-bit inputs are refused), and more than 0.1% of the pixels outside the mask and its feather band changed by over 12/255 fails. When a protected object touches the region, compare its silhouette masks before and after with `shape-check --before-mask A --after-mask B`: it fails (exit 1) when IoU drops under 0.99 (`--max-iou-loss 0.01`), the box w/h ratio changes by more than 1% (`--max-aspect 0.01`), or any outline pixel is farther than max(2 px, 0.1% of the long side) from the other outline (`--max-edge PX`); an empty or mismatched mask exits 2. The manual equivalent in a POSIX shell with ImageMagick:

```bash
src='input.png'
candidate='generated-patch.png'
mask='patch-mask.png'
x=1200
y=400
w=600
h=500

magick "$src" -crop "${w}x${h}+${x}+${y}" +repage crop.png
# Keep aspect (no "!"): crop or pad the candidate to the crop's aspect first, then run align-check.
magick "$candidate" -resize "${w}x${h}" candidate-sized.png

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

For an intended straight sword, spear, staff, or gun barrel, keep the accepted long straight part and repair the short misaligned part. This rule does not straighten an intentionally curved blade or bow, or a gun's angled grip or stock.

1. **Measure actual pixels:** on a native-size crop, observe the pommel center, crossguard center, blade-base center immediately beyond the guard, and actual blade tip; add the grip center when visible. Convert crop coordinates to final-image pixels. Record labels, dimensions, offsets, and estimated pixel uncertainty. If plausible landmark positions cross the agreed angle limit, the result is uncertain; do not report exact angular precision. Never infer a hidden point from the desired axis. If the tip is outside the frame or a landmark is ambiguous, straightness remains uncertain.
2. **Draw the guide:** use only the independently observed points. For example (illustrative coordinates, not a measurement of your image):

   ```bash
   python3 <skills>/image-verify/scripts/studio_state.py axis-check --image hero.png \
     --points 25,355 230,540 250,573 850,1570 --guide guide.png
   # pommel, crossguard, blade base, tip (pommel first, tip last); exit 1 when bent
   ```

   The rule: a straight red line from the pommel (first point) to the tip (last point) is the sword's axis. The tool traces the blade from the pixels between the last two points, outlines its edges in cyan and marks its spine in yellow, and prints how far each point and the spine sit from the red line. It fails when any of them is farther than 0.4 of the blade width (at most 3% of the sword length; `--max-offset PX` to override) or the spine tilts more than `--max-bend` degrees (default 2) against the line. Open the guide: the red line must run along the yellow spine inside the cyan outline. When the trace says "not traced", only the points were checked. Do not move the points onto the line to get exit 0.
3. **Patch only the defect:** mask the grip, pommel, and hand with enough surrounding context. Preserve the accepted long blade, subject identity, and protected cards/text. Prompt: "one straight sword, pommel, grip, guard center, blade base, and tip on the same axis at [measured angle]; the fist encloses the grip; the cape stays behind the blade." Attach the guide as geometry only; do not paint its annotations into the result. If alignment would enter a protected region, change only the short handle/hand arrangement within the permitted area; do not translate the long blade over the cards.
4. **Verify afresh:** composite through the acceptance mask and run `edit-check`. An independent reviewer observes the final landmarks again, including blade base and tip, and the caller reruns `axis-check --guide`. Save both annotated images and labeled point sets with the result. Numeric pass plus visible continuous geometry is required; ambiguous landmarks stay uncertain.
