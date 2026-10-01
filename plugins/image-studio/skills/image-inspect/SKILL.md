---
name: image-inspect
description: Diagnose what is wrong with a supplied image (crop, CSS, compression, softness, broken faces or geometry) and locate the exact object to fix, without changing pixels. Use before image-repair or for critique. Not for planning general edits (image-edit-map), JSON style extraction (image-reverse-engineer), or rebuilding a reference (image-reconstruction).
---

# Image inspection

Inspect the actual clean image at native pixels and at its intended display size, report visible defects and uncertainty, and locate the exact object to fix. This skill never changes the source. For an assessment-only request, stop after the report.

## When to use a sibling skill instead

- The whole image is soft, small, or noisy: [image-enhance](../image-enhance/SKILL.md) (it may call this skill first for a web page check).
- One object or region is wrong and the target is already clear: [image-repair](../image-repair/SKILL.md).
- The user wants an editable element map, sections, and `/edit` or `/lock` commands for planned edits: [image-edit-map](../image-edit-map/SKILL.md).

## Tools

- ImageMagick 7 (`magick`; [download](https://imagemagick.org/download/)) for file facts, crops, display-size copies, and the numbered review copy.
- An image viewer that can show 100% (one image pixel per screen pixel).
- A browser with developer tools when the image sits on a web page, to check CSS scaling, overlays, and which file the page loads.

## Steps

1. **Record file facts.** Work on copies in a working folder; keep the source untouched.
   ```bash
   magick identify -format '%f %wx%h %m %[channels] %z-bit %[colorspace] opaque=%[opaque] quality=%Q\n' source.png
   magick identify -verbose source.png | grep -E '^  (Geometry|Colorspace|Depth|Quality|Orientation):'
   ```
   `opaque=False` means the image has transparent pixels. `quality` is an estimate for JPEG and WebP; for PNG it is the compression setting, not image quality.
2. **Check the display size.** On a web page, select the image in developer tools and compare its `naturalWidth` with the rendered width × `window.devicePixelRatio`. Check `currentSrc` (the file picked from `srcset`), `object-fit`, CSS `filter` and `opacity`, and overlays. A soft look can come from upscaling by CSS, not from the file. Make a copy at the real display width (CSS width × device pixel ratio); `>` never enlarges a smaller source:
   ```bash
   magick source.png -filter Lanczos -resize '1920x>' display.png
   ```
3. **Look at 100% crops** of suspect areas (faces, hands, text, joints). The geometry is `WIDTHxHEIGHT+X+Y` in source pixels:
   ```bash
   magick source.png -crop 300x300+350+250 +repage crop-A7.png
   ```
4. **Diagnose** each finding with the defect-to-first-action table in [diagnosis.md](references/diagnosis.md). Check layout, crop, CSS effects, export quality, and source resolution before blaming image generation. Mark each finding `visible`, `inferred`, or `unknown`. Do not claim hidden content, original layers, or an exact font from a flat image.
5. **Number the targets** when the user points to one of several similar objects. Assign stable IDs in the form `A:#7` (letter for the image, number for the object) and record boxes as `[x, y, width, height]` against the **original clean image**, not a resized preview; mark each box measured or estimated. For a dense scene, map groups first and use close-ups with the same IDs. Retire an ID when its object is removed; never reuse it. Re-map after a changed source or crop. Make a separate numbered review copy only when it helps pick the target:
   ```bash
   FONT=/System/Library/Fonts/Supplemental/Arial.ttf   # macOS example; any .ttf file works
   magick source.png -fill none -stroke red -strokewidth 4 -draw 'rectangle 430,330 570,470' \
     -font "$FONT" -fill red -stroke none -pointsize 40 -annotate +430+320 '#7' review-map.png
   ```
   `rectangle` takes two corners: for box `[x, y, w, h]` write `x,y x+w,y+h`. Repeat the `-draw` and `-annotate` pair for each object. ImageMagick needs a font file to draw numbers; `magick -list font` lists registered fonts, and if it lists none, pass a `.ttf` path (Windows keeps them in `C:\Windows\Fonts`, Linux usually under `/usr/share/fonts`). The review copy is for choosing only; the clean source stays the editing input, and a box is not a segmentation mask. Inspect connected structures through supports, openings, overlaps, and paths beyond the proposed crop.
6. **Write the report** with the template below.

## Output template

```text
Source: source.png, 1600x900 PNG, 8-bit sRGB, opaque (version or date)
Display: 960 CSS px x device pixel ratio 2 = 1920 px; object-fit: cover; 40% black overlay
Findings:
1. [visible] Whole image soft at display size: 1024 px source shown at 1920 px -> image-enhance
2. [visible] A:#7 mug handle broken, box [410, 220, 180, 210] (measured) -> image-repair
3. [unknown] Headline font cannot be identified from a flat image
Object map (source pixels):
| ID   | Label         | Box [x, y, w, h]     | Measured/estimated | Protect   |
| A:#7 | held mug      | [410, 220, 180, 210] | measured           | A:#8 hand |
| A:#8 | adjacent hand | [360, 250, 100, 130] | estimated          | -         |
Review copy: review-map.png (not an edit input)
References: (ID, file, role, authority)
Unknowns: (what the image cannot establish)
Next step: (one skill and why)
```

For an edit handoff, separate observed source facts, inferred details, requested changes, protected properties, allowed physical consequences, and observable result checks, and give every reference a role and authority. [scene-contract.md](references/scene-contract.md) describes that record for multi-reference or spatially difficult scenes. The JSON form with the same IDs and source-pixel boxes is the `contract.json` in [candidate-audit.md](../image-verify/references/candidate-audit.md).

## Next step

- Whole-image softness, low resolution, or compression: [image-enhance](../image-enhance/SKILL.md).
- One wrong region (face, prop, removal, logo): [image-repair](../image-repair/SKILL.md) with the IDs and boxes above.
- Presentation problem only (crop, CSS, overlay): fix the page or framing; the pixels may be sound.
