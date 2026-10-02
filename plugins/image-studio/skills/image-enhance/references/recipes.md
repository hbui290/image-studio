# Enhancement recipes

Measured on this project's test images (a 1672×941 anime tavern scene and a dark 4096×2304 painted hero) with Upscayl's `upscayl-bin` 2.15 on Apple Silicon, using Upscayl's models plus the Real-ESRGAN-ncnn-vulkan models in one folder. Times are for the 1672×941 input. Treat them as a starting point and let `compare_display.py` decide for each image.

## Pick by image type

| Image | Recipe | Result |
| --- | --- | --- |
| Anime / 2D art, under ~2000 px wide | `remacri-4x` at 4x → Lanczos to delivery size | Best measured: clearly sharper line art, eyes, hair at 1920 and on mobile. ~31 s |
| Same, when speed matters | `realesr-animevideov3-x2` at 2x → Lanczos → `-unsharp 0x0.55+0.5+0.015` | Clearly sharper, ~2.4 s. Slight halos |
| Same, cleanest lines | `digital-art-4x` at 4x | Clean, slightly hard shading. Same weights as `realesrgan-x4plus-anime` |
| Photo | `ultrasharp-4x`, `upscayl-standard-4x`, or `realesrgan-x4plus` at 4x; compare them | Not yet verified on detailed photos; always compare |
| Already at or above delivery size but soft | No upscaler. Lanczos export, optional `-unsharp 0x0.6+0.6+0.02` | Upscaling adds little you can see; fix soft areas with image-repair |
| Small text, UI, logos | No AI upscaler | Upscalers invent wrong letters. Re-render from vector or source, or plain Lanczos |

Do not use `high-fidelity-4x` for sharpening (it softened the test image), do not run a second upscale on an enhanced image, and do not fold `-gamma`/`-brightness-contrast` into a sharpen recipe: `compare_display.py` reports that as a color shift, because it is a grade.

Upscalers amplify JPEG noise into fake texture (`ultrasharp-4x` worst). If the source is a heavily compressed JPEG, try a cleaner source first.

## Commands

`upscayl-bin` and `realesrgan-ncnn-vulkan` both accept the flags used here (`-i -o -s -m -n -t -x -g`). `upscayl-bin` has a few more (`-z`, `-r`, `-w`, `-c`) that these recipes do not need.

### Model folders

Model names are the `.param`/`.bin` file names without extension. The upscaler loads only from the folder given to `-m`, and the models come from two places:

| Models | Where they come from |
| --- | --- |
| `remacri-4x`, `ultrasharp-4x`, `digital-art-4x`, `high-fidelity-4x`, `ultramix-balanced-4x`, `upscayl-standard-4x`, `upscayl-lite-4x` | Upscayl's app models folder (macOS: `/Applications/Upscayl.app/Contents/Resources/models`) |
| `realesr-animevideov3-x2` (also `-x3`, `-x4`), `realesrgan-x4plus`, `realesrgan-x4plus-anime` | The [Real-ESRGAN-ncnn-vulkan release](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan/releases) `models` folder. They are not in Upscayl's folder |

Copy both sets into one folder of your own and point `MODELS` at it; then every recipe works with either binary. If a model is missing, `upscayl-bin` prints `fopen ... failed`, writes an all-black image, and still exits 0, so check before and after each run:

```bash
BIN=/Applications/Upscayl.app/Contents/Resources/bin/upscayl-bin   # macOS app; or upscayl-bin / realesrgan-ncnn-vulkan on PATH
MODELS=/path/to/models       # your folder holding both model sets (*.param and *.bin)
model=remacri-4x
test -f "$MODELS/$model.param" || echo "missing $model in $MODELS"
"$BIN" -i in.png -o out.png -s 4 -m "$MODELS" -n "$model"      # realesr-animevideov3-x2 uses -s 2
magick out.png -format '%[fx:maxima]' info:                  # must print a number above 0
```

Useful flags: `-t 256` (smaller tiles when memory runs out, or to avoid visible tile seams), `-x` (slower test-time augmentation, fewer seams), `-g 0` (pick the GPU). A 3840×2160 input at 4x took 160 s and about 1 GB of memory; resize from the result immediately and do not keep the 15360-wide PNG.

Some GPUs also return an all-black image with every model present; retry with `-t 32` or another model. Compare flat areas after upscaling: some models shift color slightly, which `compare_display.py` reports.

Trial on a crop first:

```bash
magick src.png -crop 500x400+1100+250 +repage crop.png
for pair in remacri-4x:4 ultrasharp-4x:4 realesr-animevideov3-x2:2; do   # model:scale
  model=${pair%:*} scale=${pair#*:}
  test -f "$MODELS/$model.param" || { echo "missing $model in $MODELS"; continue; }
  "$BIN" -i crop.png -o "crop-$model.png" -s "$scale" -m "$MODELS" -n "$model"
  echo "$model maxima: $(magick "crop-$model.png" -format '%[fx:maxima]' info:)"   # 0 = all black, discard
done
python3 <skills>/image-enhance/scripts/compare_display.py --source crop.png --candidate crop-remacri-4x.png --out c-remacri --width 1000
```

## Getting an upscaler

With authorization, install [Upscayl](https://github.com/upscayl/upscayl) (desktop app that ships `upscayl-bin` and models) or download [Real-ESRGAN-ncnn-vulkan](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan/releases) with its model files. Both run on the GPU without Python. Check the licence before redistributing either binary.

## Proving the gain

`compare_display.py` resizes the source through the same path as the candidate, so only the enhancement is measured, and fails the result when:

| Check | Fails when | Catches |
| --- | --- | --- |
| Display difference | mean change at display width < 1.0 level | Invisible edits |
| Sharpness gain | edge strength < 1.15 × baseline | Sharpen filters that do nothing visible |
| Color shift | any channel mean moves > 3 levels | Grades passed off as sharpening |
| Fidelity | reduced back to source size, PSNR < 25 dB | Invented or moved content |

On the test anime image: plain resize and a one-pixel edit failed as invisible, a strong `-unsharp` failed as not sharper, the two AI recipes passed, and the gamma grade failed on color. The numbers screen; the person decides from `before-after.png` and the crops.

## Keep small text from the source

An AI upscaler can redraw small letters into wrong ones. When an image that needs upscaling also carries a line of small text, put the plainly resized source back inside a soft box around the text (the box is in upscaled pixels):

```bash
magick src.png -filter Lanczos -resize 400% src-4x.png
magick -size 4096x6144 xc:black -fill white -draw 'rectangle 700,4900 3396,5580' -blur 0x24 -alpha off text-mask.png
magick up.png src-4x.png text-mask.png -composite locked.png
```

The mask must have no alpha channel (`-alpha off`), or the composite uses the wrong pixels. Check that the text box matches `src-4x.png` and everything outside it matches `up.png`.

## Background removal

Uses [rembg](https://github.com/danielgatis/rembg) (optional).

```bash
rembg i -m isnet-anime in.png cutout.png        # anime / illustration
rembg i -m birefnet-general in.png cutout.png   # photos and products
rembg i -a -m birefnet-general in.png cutout.png  # alpha matting for hair and fur
magick cutout.png -background white -flatten on-white.png
magick cutout.png -background black -flatten on-black.png
```

The first run downloads the model. Inspect both backdrops for halos, holes, and missing hair. Never ask an image generator for a "transparent background" and trust a painted checkerboard.

### Solid backdrop

An object on a plain black backdrop needs no segmenter. Build the mask at the source size (fill the holes so dark parts of the object stay opaque), soften it slightly, and only then enlarge it with Lanczos; a mask thresholded after upscaling keeps every stair-step. For a white backdrop, add `-negate` before `-threshold`. The hole fill starts at the top-left pixel, which must be backdrop; if the object touches that corner, change `+0+0` to a backdrop pixel.

```bash
magick in.png -colorspace gray -threshold 3% -alpha off mask.png
magick mask.png -fill white -floodfill +0+0 black -negate holes.png
magick mask.png holes.png -compose Lighten -composite -morphology Close Diamond:2 -blur 0x0.5 mask-full.png
magick in.png mask-full.png -alpha off -compose CopyOpacity -composite cutout.png
```

## Cutout edges

Symptom: a transparent PNG looks jagged, speckled, or outlined by a gray or white line on a dark or light page, though it looked fine on the backdrop it was made on. Cause: the outermost pixels still carry the old backdrop (a halo or a shadow), and an upscaler sharpened that noise. Work in this order; each step is proved with `compare_display.py`, which for transparent images also writes `before-after-light.png` and reports `edge_noise`, `edge_ratio`, `alpha_iou`, and `body_alpha` (see the SKILL.md Outputs).

1. **Check that the transparency is real.** A file can look transparent and be opaque: a painted checkerboard, or a "transparent" generator result whose background is solid black. `opaque=True` means there is no transparency; make the cutout first (rembg, or the [solid backdrop](#solid-backdrop) recipe):
   ```bash
   magick identify -format '%f opaque=%[opaque] corner=%[pixel:p{0,0}]\n' in.png
   ```
   Then run `compare_display.py` with the same file as `--source` and `--candidate` and open both before-after images. `edge_noise_source` is the edge baseline (edge noise over the noise inside the object); `body_alpha` below 254 means the object itself is slightly see-through.
2. **Upscale, if needed, before cleaning edges.** Upscayl keeps the alpha channel, so a direct run works. If the enlarged edges come out darker, give the fully transparent pixels a neutral gray, upscale the colors, and enlarge the alpha separately with Lanczos. Use `-alpha background`, which recolors only fully transparent pixels; `-alpha remove` would also blend gray into the half-transparent edge pixels and leave a gray rim once the alpha is put back:
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
5. **Regenerate the edge when shrinking is not enough**, for example a dark wavy seam that is part of the object's pixels. This is new pixels, so follow [image-repair](../../image-repair/SKILL.md): give the image generator the best cleaned version as the reference, ask for a transparent background, and repair in two passes rather than one big request:
   - Pass 1, all edges: "Edit this exact [object]. Preserve [the artwork, every line, the text "…", proportions]. Repair ONLY the outer perimeter on all four sides: clean realistic [material] edges, a smooth product-cutout silhouette with continuous antialiasing, no jagged pixels, no colored or black fringe, no stray fragments, no halo, no shadow. Same framing and dimensions. Transparent background. Add nothing."
   - Pass 2, one remaining spot, with the pass 1 result as the reference: "Local repair only. Remove [the defect] along [the exact edge]. Replace only that narrow strip with [the clean edge]. Preserve [the parts next to it] and every other pixel as closely as possible. Do not modify the other edges. Transparent background."

   A generator redraws the whole image: compare the result with the source, list any design change (a line or detail that disappeared) for the user, and composite the regenerated strip through a soft mask when the rest must stay exact. Generated files are usually about 1024 px and often have a body alpha of 249 to 254, so run steps 1, 2, and 4 on the result.

On a 4096×6144 metallic card pack shown 520 px wide (`n` = 7), `k` = 2 (a 14 px shrink with `-blur 0x3`) removed the gray side halo: `edge_ratio` 0.66, `alpha_iou` 0.987. `k` = 1 was too little (0.88) and `k` = 3 (0.80) cut further into the crimped ends, so `k` = 2 was kept. Shrinking could not remove a dark wavy seam on the top edge; two regeneration passes did. The accepted generated file was 1024×1536 with a body alpha of 249 to 254. Upscaled 4x with `ultrasharp-4x` and made solid with step 4, all three alpha methods passed at 520 px; at 2048 px, where edges are judged at the source's 1024 px, `-alpha background` measured `edge_ratio` 0.88, the direct run 0.94, and `-alpha remove` 1.22, the noisiest. `remacri-4x` shifted the average color by about 3.1 on this file and failed, so try more than one model.

## Web export

Export from the lossless master, never from a previous WebP:

```bash
mw=$(magick identify -format '%w' master.png)
for w in 3840 2560 1920 1280 768; do
  [ "$w" -gt "$mw" ] && continue   # skip widths above the master
  magick master.png -resize "${w}x>" -strip -quality 90 -define webp:method=6 "hero-$w.webp"
  magick master.png -resize "${w}x>" -strip -quality 60 "hero-$w.avif"
done
```

The width check skips any size wider than the master, so no same-size copy ships under a larger name; `>` also stops ImageMagick from upscaling. Remove skipped widths from the `srcset` below.

```html
<picture>
  <source type="image/avif" srcset="hero-768.avif 768w, hero-1280.avif 1280w, hero-1920.avif 1920w, hero-2560.avif 2560w, hero-3840.avif 3840w">
  <img src="hero-1920.webp" srcset="hero-768.webp 768w, hero-1280.webp 1280w, hero-1920.webp 1920w, hero-2560.webp 2560w, hero-3840.webp 3840w" sizes="100vw" alt="">
</picture>
```

AVIF needs an ImageMagick build with the HEIC/AVIF delegate (`magick -list format | grep AVIF`). Check that the page actually loads the new files, and compare the served file against the master at display size: in testing, re-exporting a dark 4K hero at higher quality measured better but was not visible, so compression is not always the cause.
