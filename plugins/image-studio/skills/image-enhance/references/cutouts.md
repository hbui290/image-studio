# Cutouts and transparent edges

Read by [image-enhance](../SKILL.md) only when the condition named there holds. Upscaling recipes and the measured results are in [recipes.md](recipes.md).

## Background removal

Uses [rembg](https://github.com/danielgatis/rembg) (optional).

```bash
rembg i -m isnet-anime in.png cutout.png        # anime / illustration
rembg i -m birefnet-general in.png cutout.png   # photos and products
rembg i -a -m birefnet-general in.png cutout.png  # alpha matting for hair and fur
magick cutout.png -background white -flatten on-white.png
magick cutout.png -background black -flatten on-black.png
```

Always pass `-m`: without it rembg 2.0.85 downloads `bria-rmbg` (about 1 GB, commercial use needs a BRIA licence). For a folder, `rembg p -m <model> indir outdir` loads the model once. `-dc` removes backdrop color from edge pixels. The first run downloads the model. Inspect both backdrops for halos, holes, and missing hair. Never ask an image generator for a "transparent background" and trust a painted checkerboard.

### Solid backdrop

An object on a plain black backdrop needs no segmenter. Build the mask at the source size (fill the holes so dark parts of the object stay opaque), soften it slightly, and only then enlarge it with Lanczos; a mask thresholded after upscaling keeps every stair-step. For a white backdrop, add `-negate` before `-threshold`. The hole fill starts at the top-left pixel, which must be backdrop; if the object touches that corner, change `+0+0` to a backdrop pixel.

```bash
magick in.png -colorspace gray -threshold 3% -alpha off mask.png
magick mask.png -fill white -floodfill +0+0 black -negate holes.png
magick mask.png holes.png -compose Lighten -composite -morphology Close Diamond:2 -blur 0x0.5 mask-full.png
magick in.png mask-full.png -alpha off -compose CopyOpacity -composite cutout.png
```

## Cutout edges

Symptom: a transparent PNG looks jagged, speckled, or outlined by a gray or white line on a dark or light page, though it looked fine on the backdrop it was made on. Cause: the outermost pixels still carry the old backdrop (a halo or a shadow), and an upscaler sharpened that noise. Work in this order; each step is proved with `compare_display.py`, which for transparent images also writes `before-after-light.png` and reports `edge_noise`, `edge_ratio`, `alpha_iou`, and `body_alpha` (explained in [recipes.md](recipes.md#proving-the-gain)).

1. **Check that the transparency is real.** A file can look transparent and be opaque: a painted checkerboard, or a "transparent" generator result whose background is solid black. `opaque=True` means there is no transparency; make the cutout first (rembg, or the [solid backdrop](#solid-backdrop) recipe):
   ```bash
   magick identify -format '%f opaque=%[opaque] corner=%[pixel:p{0,0}]\n' in.png
   ```
   Then run `compare_display.py` with the same file as `--source` and `--candidate` and open both before-after images. `edge_noise_source` is the edge baseline (edge noise over the noise inside the object); `body_alpha` below 254 means the object itself is slightly see-through.
2. **Upscale, if needed, before cleaning edges.** Upscayl keeps the alpha channel, so a direct run works. `$BIN`, `$MODELS`, and `$model` are set as in [recipes.md](recipes.md#commands). If the enlarged edges come out darker, give the fully transparent pixels a neutral gray, upscale the colors, and enlarge the alpha separately with Lanczos. Use `-alpha background`, which recolors only fully transparent pixels; `-alpha remove` would also blend gray into the half-transparent edge pixels and leave a gray rim once the alpha is put back:
   ```bash
   magick in.png -background '#969696' -alpha background -alpha off rgb.png
   "$BIN" -i rgb.png -o rgb-4x.png -s 4 -m "$MODELS" -n "$model"
   magick in.png -alpha extract -filter Lanczos -resize 400% alpha-4x.png
   magick rgb-4x.png alpha-4x.png -alpha off -compose CopyOpacity -composite up-4x.png
   ```
3. **Shrink the alpha edge** by one, two, and three display pixels, soften it, and compare each:
   ```bash
   src=up-4x.png                                           # the step 2 result, or in.png when step 2 was skipped
   w=520                                                   # display width in pixels
   n=$(( $(magick identify -format '%w' "$src") / w ))     # image pixels per display pixel
   n=$(( n > 0 ? n : 1 ))
   for k in 1 2 3; do
     magick "$src" \( +clone -alpha extract -morphology Erode Disk:$((k*n)) -blur 0x$((k*n/5+1)) \) \
       -compose CopyOpacity -composite "edges-$k.png"
     python3 <skills>/image-enhance/scripts/compare_display.py --source "$src" --candidate "edges-$k.png" \
       --out "edges-$k" --width "$w"
   done
   ```
   Keep the smallest shrink whose `visible_improvement` is true (edges at least 20% cleaner, `alpha_iou` at least 0.97) and that looks clean on both backdrops. Too much shrink eats thin or serrated parts: `alpha_iou` drops and the edges get noisier again. No number tells a halo from a designed gray rim, so look before accepting.
4. **Make the body solid** when `body_alpha` is below 254 and the object is not meant to be transparent. This lifts alpha 248 and above to 255 and barely touches the edge:
   ```bash
   magick in.png -channel A -level 0%,97% +channel solid.png
   ```
5. **Redraw a simple outline as a vector path** when the object has a plain geometric contour (a pack, a card, a sign) and the edge is wavy or serrated beyond what shrinking removes. Draw a smooth SVG path at the image's size that runs just inside the old edge, render it as the alpha, and look at all four sides at 100%:
   ```bash
   # outline.svg: <svg xmlns="http://www.w3.org/2000/svg" width="W" height="H"><path fill="#fff" d="M… smooth curves …Z"/></svg>
   magick -background black outline.svg -alpha off outline-mask.png
   magick in.png outline-mask.png -alpha off -compose CopyOpacity -composite outlined.png
   ```
   This changes the cutout shape on purpose, so `compare_display.py` reports a lower `alpha_iou`; verify it like step 6.
6. **Regenerate the edge when shrinking is not enough**, for example a dark wavy seam that is part of the object's pixels. This is new pixels, so follow [image-repair](../../image-repair/SKILL.md): give the image generator the best cleaned version as the reference, ask for a transparent background, and repair in two passes rather than one big request:
   - Pass 1, all edges: "Edit this exact [object]. Preserve [the artwork, every line, the text "…", proportions]. Repair ONLY the outer perimeter on all four sides: clean realistic [material] edges, a smooth product-cutout silhouette with continuous antialiasing, no jagged pixels, no colored or black fringe, no stray fragments, no halo, no shadow. Same framing and dimensions. Transparent background. Add nothing."
   - Pass 2, one remaining spot, with the pass 1 result as the reference: "Local repair only. Remove [the defect] along [the exact edge]. Replace only that narrow strip with [the clean edge]. Preserve [the parts next to it] and every other pixel as closely as possible. Do not modify the other edges. Transparent background."

   A generator redraws the whole image: compare the result with the source, list any design change (a line or detail that disappeared) for the user, and composite the regenerated strip through a soft mask when the rest must stay exact. Generated files are usually about 1024 px and often have a body alpha of 249 to 254, so run steps 1, 2, and 4 on the result.

   **Verify steps 5 and 6 with image-verify, not `compare_display.py`.** A repaired edge is new pixels: `compare_display.py` measures enhancement and reports such a change as moved content, a changed shape, or noisier edges even when it looks right. Write a [contract](../../image-verify/references/candidate-audit.md) with `change` checks for the edges and `keep` checks for logos and text, use a final acceptance mask that covers only the edge strips, and have an independent reviewer write the review.

On a 4096×6144 metallic card pack shown 520 px wide (`n` = 7), `k` = 2 (a 14 px shrink with `-blur 0x3`) removed the gray side halo: `edge_ratio` 0.66, `alpha_iou` 0.987. `k` = 1 was too little (0.88) and `k` = 3 (0.80) cut further into the crimped ends, so `k` = 2 was kept. Shrinking could not remove a dark wavy seam on the top edge; two regeneration passes did. The accepted generated file was 1024×1536 with a body alpha of 249 to 254. Upscaled 4x with `ultrasharp-4x` and made solid with step 4, all three alpha methods passed at 520 px; at 2048 px, where edges are judged at the source's 1024 px, `-alpha background` measured `edge_ratio` 0.88, the direct run 0.94, and `-alpha remove` 1.22, the noisiest. `remacri-4x` shifted the average color by about 3.1 on this file and failed, so try more than one model.
