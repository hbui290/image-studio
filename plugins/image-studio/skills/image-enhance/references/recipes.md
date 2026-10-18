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

**Transparent images.** `metrics.json` `metrics` adds `edge_width` (the width the edges are judged at: `--width`, or the source width when the display is wider, since the source has no real edge pixels beyond its own size), `edge_noise_source` and `edge_noise_candidate` (noise along the cutout edge over the noise inside the object, the worse of the dark and light backdrops; a sharper upscale raises both, a halo raises only the edge), `edge_ratio` (candidate over source; at most 0.8 with `sharpness_gain` at least 0.9 counts as a visible improvement; the candidate fails when its edge noise is above 1.35 times the source's plus 0.1, the 0.1 ignoring tiny values), `alpha_iou` (overlap of the two cutout shapes, each taken where alpha is at least half the image's highest alpha; below 0.97 fails), and `body_alpha_source` and `body_alpha` (mean alpha inside the object; a candidate below 254 that is also more see-through than the source fails, so a model trial on an already see-through crop is not failed for it). A see-through source made solid counts as a visible improvement; then `color_shift` and `fidelity_psnr` are measured with the source's opacity and the edges against the source with its body made solid, because a solid body is meant to look brighter or darker on the backdrop. Exit code 0 means the comparison ran, even when `visible_improvement` is false: read the verdict, not the exit code.

## Keep small text from the source

An AI upscaler can redraw small letters into wrong ones. When an image that needs upscaling also carries a line of small text, put the plainly resized source back inside a soft box around the text (the box is in upscaled pixels):

```bash
magick src.png -filter Lanczos -resize 400% src-4x.png
magick -size 4096x6144 xc:black -fill white -draw 'rectangle 700,4900 3396,5580' -blur 0x24 -alpha off text-mask.png
magick up.png src-4x.png text-mask.png -composite locked.png
```

The mask must have no alpha channel (`-alpha off`), or the composite uses the wrong pixels. Check that the text box matches `src-4x.png` and everything outside it matches `up.png`.

Other recipes: [cutouts and transparent edges](cutouts.md), [logo to vector](logo-vector.md), [web export](web-export.md).
