# Local repair and compositing reference

Read this when an image needs a generative patch, removal, outpaint, or controlled replacement. Adapt the geometry and tools to the input; none of the sample dimensions are universal.

## Control generated edits

- Supply the relevant crop and approved references, identifying what each controls. Specify the exact change and protected subjects, count, pose, product markings, typography, perspective, and layout. Composite approved logos or exact text from their source art.
- Prefer local repair when the composition is sound. Branch from the approved source rather than feeding each generated output into the next edit. A prompt alone cannot protect pixels outside the requested change.
- Use a crop with context for lighting and geometry, then accept only reviewed pixels through a final mask. Keep the model's input mask separate from the final acceptance mask; check polarity, full object coverage, neighboring subjects, alignment, feathered edges, and seams.
- When only an object's interior needs rebuilding, use nested masks: an outer acceptance boundary and inner protection for silhouettes, line work, logos, or other exact details. A protected exterior alone does not preserve details inside the edited object. Inspect both the protected islands and newly accepted pixels for doubled edges.
- Treat novel details as proposed art, not recovered facts. If reference material cannot establish an identity-critical feature, report the uncertainty or request a better reference instead of inventing a canonical answer.

## Before the edit

Record:

- Source image and protected reference images.
- Full image dimensions and target delivery dimensions.
- Crop rectangle `(x, y, width, height)` in **source-image pixels**.
- Allowed change and protected subjects or regions.
- Baseline full image and defect close-up at 100%.

Choose a crop slightly larger than the defect so the editor sees light, texture, and perspective. Avoid exposing unnecessary characters or text. If the source has different dimensions from a previous candidate, recalculate the crop and mask; do not reuse old pixel coordinates.

For a connected structure, trace it before generating pixels: supports and attachment points, repeated parts and their spacing, front-to-back order, and any opening or path that must remain clear. Follow rails, beams, stairs, shelves, or machine parts beyond the crop. Specify which fragments should disappear completely and what background should appear behind them. Review the resulting whole structure, not just the repaired object.

## Selecting one object in a crowded image

Before editing repeated objects, record a small map with `ID`, plain-language label, source-pixel box or crop, neighbors to protect, and edit status. `lantern-1` and `lantern-2` may share a label but must remain different targets. A box is only a locator; preview the actual mask at native pixels before accepting it. Check holes, thin parts, shadows, overlaps, and whether the mask includes a neighboring hand, face, label, or structural joint. When objects overlap, decide which one is in front and which pixels belong to each before compositing.

Manual selection is sufficient when there are few clear objects. Automatic masks can speed up a dense scene, but remain proposals: [SAM 3](https://github.com/facebookresearch/sam3) proposes masks from a text prompt or a point, and rembg's `sam` model takes a point. These are optional examples, not required dependencies or evidence of a proprietary editor's internal algorithm. Verify each proposed label, ID, and boundary against the original image. If the object is missed, draw or correct its mask manually.

Before selecting an automatic mask, check that the runtime, weights, and a sample inference actually work on this machine. If they do not, draw a manual mask or use a reviewed color/geometry selection. Record the method actually used. A named model in a setup guide is not evidence that it ran.

For a very small object in a high-resolution scene, crop around it at source resolution before requesting a mask or edit. If using overlapping tiles, retain overlap wider than the object's edge context, record every tile origin, and convert a tile-local point `(u, v)` back to source coordinates `(tile_x + u, tile_y + v)`. Reconcile duplicate detections in the overlap by visual inspection; do not merge two same-label instances only because their boxes touch. The accepted mask is drawn in source-crop coordinates after the target is chosen.

## Prompt structure

Use the form that fits the edit. Attach the actual image references.

```text
Image 1 is the source crop and fixes layout, camera angle, pose, and lighting.
Image 2 is the approved reference for [identity/material/shape], if supplied.
Change only [specific damaged object or region] by [specific correction].
Keep [subjects, count, geometry, text, branding, and nearby details] unchanged.
Match [medium, line quality or grain, perspective, light direction, palette].
Do not add [objects or content that would violate the brief].
```

For removal, describe what should be reconstructed behind the removed object. For outpainting, identify the edge to extend and which objects must not be duplicated. For face repair, the canonical character or person reference controls identity; a tiny face in a wide shot does not.

For object removal, first ask whether nearby pixels establish the hidden background. A deterministic fill or inpaint tool may suit a repeated texture; a reference-guided generative edit is appropriate when meaningful new content is needed. Neither method recovers unknowable original pixels. [LaMa's maintainer README](https://github.com/advimman/lama/blob/main/README.md) reports strong results for large masks and periodic structures, as one available approach rather than a required dependency.

Avoid vague requests such as “make it 4K and perfect.” An editor may sharpen the wrong areas or invent subject details. If the whole composition must change, treat it as a new image proposal and compare it with the original rather than calling it a repair.

## Masked composite

The example uses ImageMagick in a POSIX shell. Use an available equivalent when appropriate. Confirm that the candidate has the same aspect ratio and matching landmarks as the crop before resizing it. If it does not, align it manually or reject it; forcing a mismatched image to fit will distort the patch. From a safe working directory:

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

# Example acceptance mask in crop coordinates: white polygon accepted, black kept, 1-2 px grow and soft edge.
magick -size "${w}x${h}" xc:black -fill white \
  -draw 'polygon 120,80 480,70 520,420 90,430' \
  -morphology Dilate Disk:2 -blur 0x3 -depth 8 "$mask"
```

Create `patch-mask.png` at exactly `w × h`: white where the new pixels are accepted, black where the source must remain. Paint or draw the mask against the generated candidate, then slightly blur only the boundary. The mask is in crop-local coordinates; the composite offset is in full-image coordinates.

Check polarity separately for the generation tool and the final composite. For example, [Diffusers inpainting](https://huggingface.co/docs/diffusers/en/using-diffusers/inpaint) treats white as the area to redraw and black as the area to keep, but its generated result may still alter pixels outside the mask. The final acceptance mask remains the preservation boundary. For ImageMagick `CopyOpacity`, use a grayscale mask without an alpha channel; [its documented behavior](https://usage.imagemagick.org/compose/#copyopacity) maps black to transparent and white to opaque. OpenAI image edits read the mask's **alpha** instead: fully transparent pixels mark the area to edit, the mask must match the image size and format, and the model may still change pixels outside it. Convert this skill's white-accepts mask with `magick crop.png \( "$mask" -negate \) -alpha off -compose CopyOpacity -composite openai-mask.png` only when sending it to such a tool, and keep the original as the final acceptance mask. Preview a small patch if a tool's convention is uncertain.

Include the complete old silhouette inside the white area with a small margin where possible. A mask that cuts through an object can leave duplicate edges, partial bottles, stray foliage, or a hanging timber end. Keep protected neighbors black. If the needed mask would cut through a protected object, regenerate or redraw that edge rather than hiding the mismatch with a wider blur.

If the requested repair is **inside** an object, the outer acceptance mask is insufficient. Make a second mask for protected interior features (for example an emblem silhouette, ring, hand, or printed mark). Subtract this protection mask from the outer acceptance mask before compositing. Feather only the new boundary, check that the source and candidate features align, and reject visible ghost or doubled edges. Color thresholds may propose a mask, but inspect missed antialias pixels and similarly colored neighbors at 100% before accepting it.

```bash
magick candidate-sized.png "$mask" \
  -alpha off -compose CopyOpacity -composite patch-with-alpha.png

magick "$src" patch-with-alpha.png \
  -geometry "+${x}+${y}" -compose Over -composite -depth 8 review.png
```

`-depth 8` matters: ImageMagick may otherwise write a 16-bit PNG, which the pixel audit refuses to compare.

On Windows PowerShell, the same operations use PowerShell variables and quoting. Prepare `patch-mask.png` at the crop size first; the white/black acceptance convention is unchanged:

```powershell
$src = "input.png"
$candidate = "generated-patch.png"
$x = 1200; $y = 400; $w = 600; $h = 500
$crop = "$($w)x$($h)+$x+$y"
$offset = "+$x+$y"
magick $src -crop $crop +repage crop.png
magick $candidate -resize "$($w)x$($h)!" candidate-sized.png
magick candidate-sized.png patch-mask.png -alpha off -compose CopyOpacity -composite patch-with-alpha.png
magick $src patch-with-alpha.png -geometry $offset -compose Over -composite review.png
```

Inspect `review.png` before exporting a lossy web format. A soft mask does not correct a mismatched perspective or lighting; revise the generated patch when the seam remains visible. Keep the uncompressed review file until the final rendering is checked. Compression can alter pixels outside the patch, so compare protected regions in the uncompressed composite when exact preservation matters.

For an opaque source that must preserve all pixels outside the edit, place the crop-local final mask into a full-size black canvas at `(x, y)`. Treat every nonzero mask pixel, including the feathered boundary, as editable; invert that binary footprint to obtain the protected area. Compute a source-versus-`review.png` pixel difference only in the protected area and require zero changed pixels there. Record the count or maximum difference, then inspect the seam at 100% and the final display size. For transparent assets, include alpha in the comparison. Do this before WebP or JPEG export: lossy encoding can change pixels outside the mask even when the uncompressed composite preserved them.

If the seam has a doubled outline, first check that the generated object's landmarks align with the source crop and that the mask does not cut through both outlines. Align or regenerate the candidate before widening the feather. If the edge has a color jump, compare source and candidate profiles and adjust only the patch colors in a common colorspace. A wider blur can hide a narrow edge but cannot repair displaced geometry or a lighting mismatch.

If source and candidate colors differ, inspect embedded profiles and colorspaces before blending. Convert pixel colors into a common space when needed; do not merely relabel metadata to make them appear compatible. ImageMagick [distinguishes declaration from conversion](https://imagemagick.org/color-management/). Recheck the seam and output profile after export. Avoid routine colorspace conversion when both inputs already match.

Record a small evidence ledger for handoff: source and approved references; crop, generated candidate and accepted mask; tool/model actually invoked; dimensions before and after; rejected variants and why; 100% review and final display review. Mark an unavailable original prompt as reconstructed. Presence of an upscaler, face model, or workflow on disk is not evidence that it was used.

## Common decisions

- **Upscaling:** A 4K file can still contain soft or missing detail. For the whole image use [image-enhance](../../image-enhance/SKILL.md); for a patch, test a representative crop with a model suited to the medium, then resize the result and original to identical dimensions and compare at 100% and actual display size. Keep it only if recognizable detail improves without halos, lost line art, or invented geometry. The [Real-ESRGAN README](https://github.com/xinntao/Real-ESRGAN/blob/master/README.md) distinguishes general, anime image and anime video models. An upscaler does not establish an unknown face, product mark, or letter.
- **Portraits and characters:** Use identity references; inspect eyes, mouth, hairline, ears, hands, costume, and neighboring subjects. Keep identity and pose separate in the prompt. If using a face restorer, record the model and any fidelity setting; reject identity or hair-boundary drift. [CodeFormer](https://github.com/sczhou/CodeFormer/blob/master/README.md) documents a quality/fidelity weight and warns that whole-image face fusion can damage hair boundaries; do not assume a photoreal face model suits stylized art.
- **Products:** Verify dimensions, material, branding, labels, handles, ports, and reflected features against a real reference. A visually plausible extra part is a defect.
- **Architecture and backgrounds:** Inspect straight lines, repeated units, vanishing points, object contact, and continuity across the crop boundary.
- **Alpha cutouts:** Check the edge over both light and dark backdrops for fringe, missing hair, and holes.
- **Text and logos:** Prefer approved source art or vector and composite it after image generation. Do not rely on a generative model for exact spelling or brand geometry.
- **Marks on surfaces:** A flat corner overlay can use direct compositing. A logo printed on a tilted page or sign needs a measured perspective transform of the approved source art, then a checked mask, occlusion order, and local light/texture integration. On a strongly curved or folded surface, a simple four-corner warp may be insufficient; use a suitable surface-aware edit or keep the mark on a flatter region. Inspect recognizable proportions after projection and never substitute an AI-redrawn mark for exact brand art. A measured four-corner placement, with source corners of the logo mapped to the four measured corners on the surface:

  ```bash
  magick base.png \( logo.png -background none -virtual-pixel transparent \
    +distort Perspective '0,0 2540,1450  400,0 2700,1470  400,300 2680,1590  0,300 2520,1565' \) \
    -layers flatten -depth 8 placed.png
  ```

  The pairs are `srcX,srcY dstX,dstY` in base-image pixels. Keep `+distort` and `-layers flatten`: plain `-distort` crops the warped logo to its own small canvas, so it never reaches the target. Then mask, multiply-blend the surface texture if needed, and check the brand's usage rules; recoloring or warping a mark can break them, so say so. For a web hero headline that need not live inside the illustration, prefer editable HTML/CSS text over generated lettering. [BuilderIO's logo-composite skill](https://github.com/BuilderIO/agent-native/blob/main/templates/assets/.agents/skills/logo-composite/SKILL.md) documents the flat-overlay versus scene-surface distinction.
- **Web heroes:** Inspect desktop and mobile crops, focal subject, overlay contrast, loading behavior, and file size; verify that the actual page uses the new asset. Separate art direction (a different crop) from resolution switching (different sizes), as [MDN explains](https://developer.mozilla.org/en-US/docs/Web/HTML/Guides/Responsive_images). If the hero is the measured LCP image, check early discovery and priority; [web.dev](https://web.dev/articles/optimize-lcp) documents preloading CSS background LCP images in the initial HTML. Do not preload every decorative background.

When two candidates repeat the same failure, change the approach rather than only rewriting adjectives in the prompt. Narrow or relocate the crop, use a stronger reference, change the mask, use a deterministic edit, or report that the source lacks enough information.
