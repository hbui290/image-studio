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

```bash
BIN=/Applications/Upscayl.app/Contents/Resources/bin/upscayl-bin   # macOS app; or upscayl-bin / realesrgan-ncnn-vulkan on PATH
MODELS=/Applications/Upscayl.app/Contents/Resources/models        # or your own folder holding *.param/*.bin
"$BIN" -i in.png -o out.png -s 4 -m "$MODELS" -n remacri-4x
"$BIN" -i in.png -o out.png -s 2 -m "$MODELS" -n realesr-animevideov3-x2
```

Model names are the `.param`/`.bin` file names without extension. Upscayl ships `remacri-4x`, `ultrasharp-4x`, `digital-art-4x`, `high-fidelity-4x`, `ultramix-balanced-4x`, `upscayl-standard-4x`, and `upscayl-lite-4x`. `realesr-animevideov3-x2` (also `-x3`, `-x4`), `realesrgan-x4plus`, and `realesrgan-x4plus-anime` come with the [Real-ESRGAN-ncnn-vulkan release](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan/releases); copy their files into one models folder to use every model with either binary. Useful flags: `-t 256` (smaller tiles when memory runs out, or to avoid visible tile seams), `-x` (slower test-time augmentation, fewer seams), `-g 0` (pick the GPU). A 3840×2160 input at 4x took 160 s and about 1 GB of memory; resize from the result immediately and do not keep the 15360-wide PNG.

Some GPUs return an all-black image; check the output before using it, then retry with `-t 32` or another model. Compare flat areas after upscaling: some models shift color slightly, which `compare_display.py` reports.

Trial on a crop first:

```bash
magick src.png -crop 500x400+1100+250 +repage crop.png
for pair in remacri-4x:4 ultrasharp-4x:4 realesr-animevideov3-x2:2; do   # model:scale
  model=${pair%:*} scale=${pair#*:}
  "$BIN" -i crop.png -o "crop-$model.png" -s "$scale" -m "$MODELS" -n "$model"
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

## Background removal

```bash
rembg i -m isnet-anime in.png cutout.png        # anime / illustration
rembg i -m birefnet-general in.png cutout.png   # photos and products
rembg i -a -m birefnet-general in.png cutout.png  # alpha matting for hair and fur
magick cutout.png -background white -flatten on-white.png
magick cutout.png -background black -flatten on-black.png
```

The first run downloads the model. Inspect both backdrops for halos, holes, and missing hair. Never ask an image generator for a "transparent background" and trust a painted checkerboard.

## Web export

Export from the lossless master, never from a previous WebP:

```bash
for w in 3840 2560 1920 1280 768; do
  magick master.png -resize "${w}x" -strip -quality 90 -define webp:method=6 "hero-$w.webp"
  magick master.png -resize "${w}x" -strip -quality 60 "hero-$w.avif"
done
```

```html
<picture>
  <source type="image/avif" srcset="hero-768.avif 768w, hero-1280.avif 1280w, hero-1920.avif 1920w, hero-2560.avif 2560w, hero-3840.avif 3840w">
  <img src="hero-1920.webp" srcset="hero-768.webp 768w, hero-1280.webp 1280w, hero-1920.webp 1920w, hero-2560.webp 2560w, hero-3840.webp 3840w" sizes="100vw" alt="">
</picture>
```

AVIF needs an ImageMagick build with the HEIC/AVIF delegate (`magick -list format | grep AVIF`). Check that the page actually loads the new files, and compare the served file against the master at display size: in testing, re-exporting a dark 4K hero at higher quality measured better but was not visible, so compression is not always the cause.
