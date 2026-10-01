---
name: image-enhance
description: Make a whole image look sharper, cleaner, or larger - blurry, soft, pixelated, low resolution, "upscale", "make it 4K", "enhance", "smoother" - with an AI upscaler plus ImageMagick, then prove the result is visibly better at display size. Also background removal and web export. Not for fixing one wrong object (image-repair).
---

# Whole-image enhancement

The upscaler and `magick` do the work; this skill picks the recipe and proves the gain. A bigger file is not a better image: accept only what `compare_display.py` and a look at `before-after.png` confirm.

1. **Diagnose first** with [image-inspect](../image-inspect/SKILL.md) when the image sits on a page: CSS scaling, dark overlays, and heavy compression can make a good file look soft. If the served file is soft but the master is sharp, re-export from the master instead.
2. **Find the tools** (never assume, never skip one that is present):
   ```bash
   command -v magick upscale realesrgan-ncnn-vulkan upscayl-bin
   ls /Applications/Upscayl.app/Contents/Resources/bin/ ~/.local/share/realesrgan/models 2>/dev/null
   ```
   If no upscaler exists, say so and offer [setup](references/recipes.md#getting-an-upscaler); do not pass off a sharpen filter as enhancement.
3. **Pick the recipe by image type** from [recipes.md](references/recipes.md). Default for anime/2D art under about 2000 px wide: `remacri` 4x, or `realesr-animevideov3` 2x when speed matters. Never upscale small text or UI; never repeat a pass on an already enhanced image.
4. **Trial on a crop** of the softest area (faces, small props) with two or three models, then run the winner on the whole image and resize to the delivery size:
   ```bash
   upscale src.png up.png remacri 4          # or: upscale src.png up.png realesr-animevideov3-x2 2
   magick up.png -filter Lanczos -resize 3840x2160 -depth 8 enhanced.png
   ```
   The origin recipe adds `-unsharp 0x0.55+0.5+0.015` after the resize. `-depth 8` keeps a 16-bit PNG from being produced.
5. **Prove it** at the real display size, with 100% crops of the areas the user cares about:
   ```bash
   python3 <skills>/image-enhance/scripts/compare_display.py --source src.png --candidate enhanced.png \
     --out compare-1 --width 1920 --crop 1200,300,400,300
   ```
   `visible_improvement: false` means stop and report what failed (invisible, not sharper, color shifted, or content moved). Show `before-after.png` and the crops to the user either way. Record rejected models in one line each.
6. **If still soft where it matters** (faces, props with no real detail), the pixels do not exist: hand those regions to [image-repair](../image-repair/SKILL.md) with references. Upscalers sharpen what is there; they do not invent a correct face.
7. **Deliver** with the [export](references/recipes.md#web-export) and [cutout](references/recipes.md#background-removal) recipes. A brightness or color grade is a separate, requested change, not part of sharpening.

Run scripts with `python3` 3.9+ and Pillow (`uv run --with pillow python3 ...` works without installing). `<skills>` is the folder that holds the skill folders.
