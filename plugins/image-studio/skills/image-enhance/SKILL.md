---
name: image-enhance
description: Make a whole image look sharper, cleaner, or larger - blurry, soft, pixelated, low resolution, "upscale", "make it 4K", "enhance", "smoother" - with an AI upscaler plus ImageMagick, then prove the result is visibly better at display size. Also jagged, speckled, or haloed edges on a transparent PNG, background removal, and web export. Not for fixing one wrong object (image-repair).
---

# Whole-image enhancement

The upscaler and `magick` do the work; this skill picks the recipe and proves the gain. A bigger file is not a better image: accept only what `compare_display.py` and a look at `before-after.png` confirm.

A worked case that combines a repaint, an upscale, and masked repairs is the [tavern hero example](https://github.com/hbui290/image-studio/blob/main/examples/image-repair/tavern-hero-case.md) in the repository; a skills install does not include it.

## When to use a sibling skill

- One wrong object, a bad face, or a local defect: [image-repair](../image-repair/SKILL.md). Upscalers sharpen what is there; they do not invent correct detail.
- The image looks soft only on a web page, or you do not yet know why it looks bad: [image-inspect](../image-inspect/SKILL.md) first.
- A new image or a generate-and-review cycle: [image-loop](../image-loop/SKILL.md).

## Tools

- Required: [ImageMagick](https://imagemagick.org) (`magick`), and one upscaler: [Upscayl](https://github.com/upscayl/upscayl) (`upscayl-bin`) or [Real-ESRGAN-ncnn-vulkan](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan/releases) (`realesrgan-ncnn-vulkan`), with its model files.
- Optional: [rembg](https://github.com/danielgatis/rembg) for [background removal](references/recipes.md#background-removal).
- Python 3.9+ with Pillow for `compare_display.py`: `uv run --with pillow python3 ...` ([uv](https://docs.astral.sh/uv/)) works without installing; otherwise `python3 -m pip install pillow`. `<skills>` is the folder that holds the skill folders.

## Steps

1. **Diagnose first** with [image-inspect](../image-inspect/SKILL.md) when the image sits on a page: CSS scaling, dark overlays, and heavy compression can make a good file look soft. If the served file is soft but the master is sharp, re-export from the master instead.
2. **Find the tools** (never assume, never skip one that is present):
   ```bash
   command -v magick upscayl-bin realesrgan-ncnn-vulkan
   ls /Applications/Upscayl.app/Contents/Resources/bin/ 2>/dev/null   # macOS app; elsewhere look in the Upscayl install folder
   ```
   Paths under `/Applications` here and in [recipes.md](references/recipes.md) are macOS examples; on Windows and Linux, look in the folder where Upscayl or Real-ESRGAN-ncnn-vulkan was installed. If no upscaler exists, say so and offer [setup](references/recipes.md#getting-an-upscaler); do not pass off a sharpen filter as enhancement.
3. **Pick the recipe by image type** from [recipes.md](references/recipes.md). Default for anime/2D art under about 2000 px wide: `remacri-4x` at 4x, or `realesr-animevideov3-x2` at 2x when speed matters. Never upscale small text or UI; never repeat a pass on an already enhanced image.
4. **Trial on a crop** of the softest area (faces, small props) with two or three models, then run the winner on the whole image and resize to the delivery size:
   ```bash
   BIN=upscayl-bin              # the binary found in step 2 (full path for the macOS app), or realesrgan-ncnn-vulkan
   MODELS=/path/to/models       # one folder holding every model's .param and .bin; see "Model folders" in recipes.md
   model=remacri-4x             # or realesr-animevideov3-x2 with -s 2
   test -f "$MODELS/$model.param" || echo "missing $model in $MODELS"
   "$BIN" -i src.png -o up.png -s 4 -m "$MODELS" -n "$model"
   magick up.png -format '%[fx:maxima]' info:     # must print a number above 0; 0 means an all-black image
   magick up.png -filter Lanczos -resize 3840x2160 -depth 8 enhanced.png
   ```
   A missing model does not stop the upscaler: it prints `fopen ... failed`, writes an all-black image, and still exits 0. The Upscayl app's own models folder holds only the seven Upscayl models; the `realesr-*` and `realesrgan-*` models must be copied in from the Real-ESRGAN-ncnn-vulkan release ([model folders](references/recipes.md#model-folders)). The fast `realesr-animevideov3-x2` recipe adds `-unsharp 0x0.55+0.5+0.015` after the resize. `-depth 8` keeps a 16-bit PNG from being produced.
5. **Prove it** at the real display size, with 100% crops of the areas the user cares about:
   ```bash
   python3 <skills>/image-enhance/scripts/compare_display.py --source src.png --candidate enhanced.png \
     --out compare-1 --width 1920 --crop 1200,300,400,300
   ```
   `--width` is the display width in pixels (CSS width × device pixel ratio), 1 to 16384. Transparent images are compared on a dark backdrop, with a light-backdrop copy for viewing, and their cutout edges are checked too (see Outputs). A cutout made from an opaque image is a new shape, not an enhancement: inspect it with the [background removal](references/recipes.md#background-removal) backdrops instead.
   `visible_improvement: false` means stop and report what failed (invisible, not sharper, color shifted, or content moved). Show `before-after.png` and the crops to the user either way. Record rejected models in one line each.
6. **Transparent PNG with jagged or outlined edges**: the halo is in the alpha edge, so upscaling only enlarges it. After any upscale, clean the edges with the [cutout edges](references/recipes.md#cutout-edges) recipe and prove it with step 5.
7. **If still soft where it matters** (faces, props with no real detail), the pixels do not exist: hand those regions to [image-repair](../image-repair/SKILL.md) with references.
8. **Deliver** with the [export](references/recipes.md#web-export) and [cutout](references/recipes.md#background-removal) recipes. A brightness or color grade is a separate, requested change, not part of sharpening.

## Outputs

`compare_display.py` creates the `--out` folder and writes:

- `metrics.json`: `visible_improvement`, `failures`, `metrics`, and `limits`. The same JSON is printed to stdout. For transparent images, `metrics` adds `edge_speckle_source` and `edge_speckle_candidate` (edge noise at display size, the worse of the dark and light backdrops), `edge_ratio` (candidate over source; at most 0.8 counts as a visible improvement, above 1.1 fails), and `alpha_iou` (overlap of the two cutout shapes; below 0.97 fails).
- `before-after.png`: source left, candidate right, both resized to `--width`. Transparent images are shown on a dark backdrop.
- `before-after-light.png`: the same on a light backdrop, written only when either image has transparent pixels.
- `crop-N.png`: one 100% crop pair per `--crop`, numbered from 1.

Exit codes: 0 whenever the comparison ran, including when `visible_improvement` is false, so read the verdict, not the exit code. 2 for bad input: a missing or unreadable file, an existing `--out` folder, a `--width` outside 1 to 16384, different aspect ratios, or a crop outside the source.

## Stop conditions

- No upscaler is installed: say so and offer setup; do not substitute a sharpen filter.
- A model file is missing from `$MODELS`, or the output is all black (`%[fx:maxima]` prints 0): do not use that output. Fix the models folder, or retry with `-t 32` or another model.
- `visible_improvement` is false for every model tried: stop and report the failures with `before-after.png`.
- The image is small text, UI, or a logo: do not use an AI upscaler.
- Remaining softness is missing detail, not blur: hand those regions to image-repair.
- Every edge shrink either leaves the edges noisy or drops `alpha_iou` below 0.97: stop and show both before-after images; the halo needs a masked fix in image-repair.
