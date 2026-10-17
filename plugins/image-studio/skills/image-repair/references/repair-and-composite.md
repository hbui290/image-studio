# Local repair and compositing reference

Read this when an image needs a generative patch, removal, outpaint, or controlled replacement. Adapt geometry and tools to the input; sample dimensions are illustrative.

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

For removal, describe what should appear behind the removed object (texture fill for periodic patterns, reference-guided generation for new content; see [LaMa](https://github.com/advimman/lama) for inpainting). For outpainting, identify edges to extend and objects not to duplicate. For face repair, canonical character references control identity. Avoid vague requests such as "make it 4K".

## Masked composite

Confirm the generated candidate matches the crop's aspect ratio and landmarks before resizing. In a POSIX shell with ImageMagick:

```bash
src='input.png'
candidate='generated-patch.png'
mask='patch-mask.png'
x=1200
y=400
w=600
h=500

magick "$src" -crop "${w}x${h}+${x}+${y}" +repage crop.png
magick "$candidate" -resize "${w}x${h}!" candidate-sized.png

# Acceptance mask in crop coordinates: white polygon accepted, black kept, 1-2 px grow and soft edge.
magick -size "${w}x${h}" xc:black -fill white \
  -draw 'polygon 120,80 480,70 520,420 90,430' \
  -morphology Dilate Disk:2 -blur 0x3 -depth 8 "$mask"

magick candidate-sized.png "$mask" \
  -alpha off -compose CopyOpacity -composite patch-with-alpha.png

magick "$src" patch-with-alpha.png \
  -geometry "+${x}+${y}" -compose Over -composite -depth 8 review.png
```

Create `patch-mask.png` at exactly `w × h`: white accepts new pixels, black keeps the source. Feather only the boundary.
- **Polarity:** The final acceptance mask uses white for accepted pixels and black for kept pixels. For tools requiring inverted alpha (such as OpenAI edits where transparent pixels mark areas to redraw), convert with `magick crop.png \( "$mask" -negate \) -alpha off -compose CopyOpacity -composite openai-mask.png`, keeping the original as the acceptance mask.
- **Coverage:** Include complete silhouettes with a small margin. If a mask cuts through an object, regenerate or redraw rather than hiding mismatches with wide blur.
- **Nested masks:** For interior repairs, subtract protected interior masks (emblems, line work) from the outer acceptance mask before compositing.
- **`-depth 8`:** Required to ensure 8-bit PNG output that pixel audit scripts can compare. On Windows PowerShell, use equivalent variables (`$crop = "$($w)x$($h)+$x+$y"`) with the same white-accepts convention.

Inspect `review.png` before lossy export. For exact preservation outside edits, place the crop-local mask on a full-size black canvas at `(x, y)`, invert the nonzero mask footprint to obtain the protected area, and verify zero changed pixels there. Inspect seams at 100% and delivery size. If colors differ, convert profiles into a common colorspace before blending rather than relabeling metadata ([ImageMagick color management](https://imagemagick.org/color-management/)).

Record an evidence ledger: source and approved references; crop, candidate, and accepted mask; tool/model invoked; dimensions before/after; rejected variants and why; 100% review and final display review.

## Common decisions

- **Upscaling:** Test a representative crop with a suited model ([Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)); compare at 100% and display size. For whole images use [image-enhance](../../image-enhance/SKILL.md). Upscaling cannot establish unknown details.
- **Portraits and characters:** Use identity references; inspect eyes, hairline, hands, and costume. For face restorers ([CodeFormer](https://github.com/sczhou/CodeFormer)), watch fidelity weights and hair boundaries.
- **Products:** Verify dimensions, material, markings, handles, and reflections against real references. Plausible extra parts are defects.
- **Architecture and backgrounds:** Verify straight lines, vanishing points, repeated units, and continuity across crop boundaries.
- **Alpha cutouts:** Check edges over light and dark backdrops for fringes, missing hair, and holes.
- **Text and logos:** Follow [repair-rules.md](repair-rules.md) for clean plates, alpha extraction, and per-occurrence checks. Composite approved source art or vector after generation; never rely on generators for exact spelling or brand geometry. Rebuild raster marks with [logo to vector](../../image-enhance/references/recipes.md#logo-to-vector).
- **Marks on surfaces:** Tilted surfaces require a measured perspective transform of approved art, checked masks, and light/texture blending. Source corners map to four measured surface corners (`srcX,srcY dstX,dstY`):

  ```bash
  magick base.png \( logo.png -background none -virtual-pixel transparent \
    +distort Perspective '0,0 2540,1450  400,0 2700,1470  400,300 2680,1590  0,300 2520,1565' \) \
    -layers flatten -depth 8 placed.png
  ```

  Keep `+distort` and `-layers flatten` so the warped logo reaches target coordinates. For flat overlays versus scene surfaces, see [BuilderIO logo-composite](https://github.com/BuilderIO/agent-native/blob/main/templates/assets/.agents/skills/logo-composite/SKILL.md).
- **Web heroes:** Inspect desktop and mobile crops, focal subjects, overlay contrast, and file size ([MDN responsive images](https://developer.mozilla.org/en-US/docs/Web/HTML/Guides/Responsive_images)). For LCP images, check discovery and priority ([web.dev optimize LCP](https://web.dev/articles/optimize-lcp)).
