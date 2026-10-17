---
name: image-inspect
description: "Diagnose defects, critique image, inspect crop, check CSS, or locate object: inspect images at native pixels and display size, report visible defects and uncertainty, and map targets with stable IDs without changing pixels."
---

# Image inspection

Inspect clean images at native pixels and display size, report visible defects, and locate objects to fix without altering source pixels.

Routing: For whole-image softness/upscaling use [image-enhance](../image-enhance/SKILL.md); for local fixes use [image-repair](../image-repair/SKILL.md); for interactive planning use [image-edit-map](../image-edit-map/SKILL.md).

## Operational checklist

1. **Tools & isolation:** Work on copies; keep source untouched. Use ImageMagick 7 (`magick`; [download](https://imagemagick.org/download/)) and a 100% pixel viewer.
2. **File facts:** Record geometry, channels, depth, colorspace, alpha, and quality:
   ```bash
   magick identify -format '%f %wx%h %m %[channels] %z-bit %[colorspace] opaque=%[opaque] quality=%Q\n' source.png
   ```
3. **Display size:** For web images, use browser devtools to check `naturalWidth` vs CSS width × DPR, `currentSrc`, `object-fit`, and CSS filters. Create a display-width copy (`>` avoids enlarging smaller sources):
   ```bash
   magick source.png -filter Lanczos -resize '1920x>' display.png
   ```
4. **100% crops:** Inspect suspect details (faces, hands, text, seams) at source resolution (`WIDTHxHEIGHT+X+Y`):
   ```bash
   magick source.png -crop 300x300+350+250 +repage crop-A7.png
   ```
5. **Diagnose:** Mark each finding visible, inferred, or unknown. Do not claim hidden layers or exact fonts from flat images. Read [diagnosis.md](references/diagnosis.md) only when diagnosing specific defect categories.
6. **Number targets:** Assign stable IDs (`A:#7`) and measured/estimated boxes `[x, y, w, h]` against the clean original. Retire removed IDs. If a numbered review copy helps choose targets:
   ```bash
   FONT=/System/Library/Fonts/Supplemental/Arial.ttf
   magick source.png -fill none -stroke red -strokewidth 4 -draw 'rectangle 430,330 570,470' \
     -font "$FONT" -fill red -stroke none -pointsize 40 -annotate +430+320 '#7' review-map.png
   ```
7. **Report:** Output source facts, display facts, findings, object map, references, unknowns, and next step. Read [scene-contract.md](references/scene-contract.md) only when writing an edit contract for complex or multi-reference scenes.
