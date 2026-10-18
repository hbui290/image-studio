# Logo to vector

Read by [image-enhance](../SKILL.md) only when the condition named there holds. Upscaling recipes and the measured results are in [recipes.md](recipes.md).

A flat logo (a few solid colors) is rebuilt as SVG paths with [Potrace](https://potrace.sourceforge.net), one layer per color, instead of being upscaled. Make a 1-bit mask per color (`-fuzz` sets how close a pixel must be to the color; `-alpha remove` puts transparent areas on white, because `-alpha off` would expose whatever color hides under them), trace each mask, and stack the layers bottom to top in the logo's own order:

```bash
for layer in '000000:black' '00cfd0:cyan'; do      # color:name, bottom layer first
  magick logo.png -background white -alpha remove -fuzz 25% -fill '#ff00ff' -opaque "#${layer%%:*}" \
    -fuzz 0 -fill white +opaque '#ff00ff' -fill black -opaque '#ff00ff' "${layer##*:}.pbm"
  potrace --svg --turdsize 8 --alphamax 1 --opttolerance 0.2 --color "#${layer%%:*}" -o "${layer##*:}.svg" "${layer##*:}.pbm"
done
sed -e 's/pt"/"/g' -e '/<\/svg>/d' black.svg > logo.svg   # first layer keeps the header; sizes in pixels, not points
sed -n '/<g /,/<\/g>/p' cyan.svg >> logo.svg             # repeat for every further layer
echo '</svg>' >> logo.svg
```

Check it: render the SVG at the logo's size, rebuild each color mask from the render with the same command, and compare. Differing pixels should be a few percent of the color's pixels; thin strokes differ more. On a 2172×724 two-color logo the black layer differed by about 2% and the thin cyan strokes by about 7%; the file had 15 paths and no embedded image.

```bash
magick -background white logo.svg -alpha off render.png
magick render.png -background white -alpha remove -fuzz 25% -fill '#ff00ff' -opaque '#00cfd0' \
  -fuzz 0 -fill white +opaque '#ff00ff' -fill black -opaque '#ff00ff' cyan-render.pbm
magick compare -metric AE cyan.pbm cyan-render.pbm null:              # differing pixels (printed to stderr)
magick cyan.pbm -format '%[fx:round((1-mean)*w*h)]\n' info:          # the color's pixels
grep -c '<image' logo.svg                                             # must print 0: no embedded raster
```

Place a vector logo on artwork by compositing the SVG itself, never by asking an image generator to redraw it ([text and logos](../../image-repair/references/subject-checks.md)).
