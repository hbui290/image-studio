# Web export

Read by [image-enhance](../SKILL.md) only when the condition named there holds. Upscaling recipes and the measured results are in [recipes.md](recipes.md).

Export from the lossless source file, never from a previous WebP. `-strip` drops the color profile, so first convert a master tagged Display P3, Adobe RGB, or another non-sRGB profile into sRGB, or its colors shift in the browser:

```bash
magick identify -format '%[profile:icc]\n' source.png 2>/dev/null   # empty or sRGB: skip the next line
magick source.png -profile "/System/Library/ColorSync/Profiles/sRGB Profile.icc" source-srgb.png   # macOS path; elsewhere any sRGB .icc file; then export from source-srgb.png
```

```bash
mw=$(magick identify -format '%w' source.png)
for w in 3840 2560 1920 1280 768; do
  [ "$w" -gt "$mw" ] && continue   # skip widths above the source
  magick source.png -resize "${w}x>" -strip -quality 90 -define webp:method=6 "hero-$w.webp"
  magick source.png -resize "${w}x>" -strip -quality 60 "hero-$w.avif"
done
```

The width check skips any size wider than the source, so no same-size copy ships under a larger name; `>` also stops ImageMagick from upscaling. Remove skipped widths from the `srcset` below.

```html
<picture>
  <source type="image/avif" srcset="hero-768.avif 768w, hero-1280.avif 1280w, hero-1920.avif 1920w, hero-2560.avif 2560w, hero-3840.avif 3840w">
  <img src="hero-1920.webp" srcset="hero-768.webp 768w, hero-1280.webp 1280w, hero-1920.webp 1920w, hero-2560.webp 2560w, hero-3840.webp 3840w" sizes="100vw" alt="">
</picture>
```

AVIF needs an ImageMagick build with the HEIC/AVIF delegate (`magick -list format | grep AVIF`). Check that the page actually loads the new files, and compare the served file against the master at display size: in testing, re-exporting a dark 4K hero at higher quality measured better but was not visible, so compression is not always the cause.
