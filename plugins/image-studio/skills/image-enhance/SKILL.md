---
name: image-enhance
description: "Upscale, sharpen, blurry, soft, pixelated, low resolution, 4K, enhance, clean edges, SVG logo, remove background: improve whole image, prove visible gain with compare_display.py. Not for local fixes (image-repair)."
---

# Whole-image enhancement

Improve a whole image and prove visible gain at display size without altering source pixels.

Routing: For single-region fixes use [image-repair](../image-repair/SKILL.md); to diagnose blur use [image-inspect](../image-inspect/SKILL.md); for iterative generation use [image-loop](../image-loop/SKILL.md).

Worked case (repo checkout only): [tavern hero example](https://github.com/hbui290/image-studio/blob/main/examples/image-repair/tavern-hero-case.md).

Run scripts; do not read their source - use `--help` for usage.

## Operational checklist

0. **Memory:** If not in context, run `python3 <skills>/image-verify/scripts/studio_state.py brief` (no store: `taste list` and `lesson list` instead) (see [using the store in a skill](../image-verify/references/project-memory.md#using-the-store-in-a-skill)). Read this file and each reference once per chat, and open each new result once.
1. **Diagnose:** Check web images with [image-inspect](../image-inspect/SKILL.md) for CSS scaling or compression first.
2. **Find tools:** Detect [ImageMagick](https://imagemagick.org) `magick` and an upscaler ([Upscayl](https://github.com/upscayl/upscayl) `upscayl-bin`, [Real-ESRGAN-ncnn-vulkan](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan) `realesrgan-ncnn-vulkan`):
   ```bash
   command -v magick upscayl-bin realesrgan-ncnn-vulkan
   ls /Applications/Upscayl.app/Contents/Resources/bin/ 2>/dev/null
   ```
   Stop if an upscale is needed and no upscaler is installed; do not use sharpen filter. Read [recipes.md](references/recipes.md#getting-an-upscaler) only when installing upscaler.
3. **Pick recipe:** Read [recipes.md](references/recipes.md#pick-by-image-type) only when choosing a model recipe (`remacri-4x` at 4x, non-commercial, else `digital-art-4x`; or `realesr-animevideov3-x2` at 2x). Never AI-upscale small text or UI; read [recipes.md](references/recipes.md#keep-small-text-from-the-source) only when locking text. Rebuild flat logos as SVG; read [logo-vector.md](references/logo-vector.md) only when vectorizing.
4. **Trial & upscale:** Test on a crop of the softest area, then run winner on whole image:
   ```bash
   BIN=/Applications/Upscayl.app/Contents/Resources/bin/upscayl-bin   # macOS app; or upscayl-bin / realesrgan-ncnn-vulkan on PATH
   MODELS=/path/to/models; model=remacri-4x
   test -f "$MODELS/$model.param" || echo "missing $model in $MODELS"
   "$BIN" -i src.png -o up.png -s 4 -m "$MODELS" -n "$model"
   magick up.png -alpha off -format '%[fx:maxima]' info:
   magick up.png -filter Lanczos -resize 3840x -depth 8 enhanced.png
   ```
   If a model is missing or `%[fx:maxima]` is 0, retry once with `-t 32` or another model; stop if it is still 0. Fast anime: `-unsharp 0x0.55+0.5+0.015`. `-depth 8` avoids 16-bit PNG. Read [recipes.md](references/recipes.md#model-folders) only when configuring model folders.
5. **Prove improvement:** Compare at display width with 100% crops:
   ```bash
   python3 <skills>/image-enhance/scripts/compare_display.py --source src.png --candidate enhanced.png \
     --out compare-1 --width 1920 --crop 1200,300,400,300
   ```
   Run: `uv run --with pillow python3 <skills>/image-enhance/scripts/compare_display.py ...` ([uv](https://docs.astral.sh/uv/)) (fallback: `python3 -m pip install pillow`). Stop if `visible_improvement` is false; show `before-after.png`. Outputs: `--out/metrics.json` (`visible_improvement`, `failures`, `metrics`, `limits`), `before-after.png`, `before-after-light.png` (transparent images only), `crop-N.png`. Exit codes: 0 (ran), 2 on bad input (`--width` 1..16384, float/aspect/crop error). Read [recipes.md](references/recipes.md#proving-the-gain) only when evaluating metrics, including the transparent-image edge and alpha metrics. Read [cutouts.md](references/cutouts.md#background-removal) only when checking backdrops.
6. **Cutout edges:** For transparent PNG with halos, read [cutouts.md](references/cutouts.md#cutout-edges) only when fixing cutout edges. Stop if shrinking leaves noise or drops `alpha_iou` below 0.97; regenerate edge via [image-repair](../image-repair/SKILL.md).
7. **Handoff:** If soft from missing detail, hand regions to [image-repair](../image-repair/SKILL.md).
8. **Export:** Read [web-export.md](references/web-export.md) only when exporting for web.
9. **Gate before claiming done:** In a project with a store, run `gate --deliverable` once before claiming done; follow [using the store in a skill](../image-verify/references/project-memory.md#using-the-store-in-a-skill).
