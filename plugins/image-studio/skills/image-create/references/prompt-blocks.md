# Prompt blocks

Read by [image-create](../SKILL.md) when writing a generation prompt. A prompt built from fixed blocks gives stable results across images and turns, so the user's style does not drift from one asset to the next.

## 1. Style block (same text at the start of every prompt in a task)

Fill it once per brand from `brand show` (palette, fonts, do and don't), the user's taste notes, and confirmed preferences, then paste it unchanged:

```text
Style: <medium, e.g. polished 2D hand-painted game art / flat vector / product photo>, <view, e.g. three-quarter top-down>,
<rendering, e.g. soft painterly shading, clean readable silhouettes, not a 3D render>. Mood: <mood>.
Use only this palette: <name #HEX (role)>, <name #HEX (role)>, ...
Lighting: <direction and color of key and rim light>.
No text, letters, numbers, logos, watermarks or signatures<, no people / animals if not wanted>.
```

Use measured values (hex colors, light direction, view angle), not adjectives alone. Never write "in the style of <another artist, game, or company>".

## 2. The item (one item per image)

Describe one asset per image: subject, shape, proportions or aspect ratio, what must be empty (space for a title or logo added later). Generators write text and logos badly: leave that space empty in the image and add exact text and the user's logo file afterwards with `compose_layers.py` ([image-create](../SKILL.md) step 3).

## 3. Background rule (end of the prompt, by asset type)

| Asset | Add |
|---|---|
| Object or ornament to cut out | `Isolated on a perfectly flat solid pure magenta (#FF00FF) background, no gradient, no shadow on the background, crisp edges, generous empty margin. Do not use magenta or pink anywhere in the object.` |
| Glow, light, or particle effect | `On a pure black (#000000) background; the effect fades smoothly into black. Nothing else in the image.` |
| Full scene or background | No background rule; say what stays empty and where. |

In Codex, prefer `image_gen.imagegen` with `transparent_background`; use the magenta background only when the tool cannot give transparency. Magenta separates cleanly from dark or navy subjects where black does not. Key it out with [ImageMagick](https://imagemagick.org) so the edges get soft alpha and the magenta is removed from their color (a plain `-fuzz 15% -transparent '#FF00FF'` leaves a pink rim that later edge steps make worse):

```bash
magick in.png -alpha off \( +clone -fx 'clamp((1-(min(r,b)-g)-0.10)/0.85)' \) -compose CopyOpacity -composite \
  -channel R -fx 'clamp((r-(1-a))/max(a,0.004))' -channel G -fx 'clamp(g/max(a,0.004))' \
  -channel B -fx 'clamp((b-(1-a))/max(a,0.004))' +channel cutout.png
magick cutout.png -fx 'a>0.02 && (min(r,b)-g)>0.08' -alpha off -format '%[fx:round(mean*w*h)]' info:   # pink rim pixels: should be 0
```

Purple or pink parts of the object would turn see-through, which is why the prompt bans them. Then check edges with [cutout edges](../../image-enhance/references/cutouts.md#cutout-edges).

## 4. References

Attach the actual files and give each one a role: `Image 1 is the approved style reference: match its line weight, shading, and palette exactly. Image 2 fixes the product shape.` Use only files the user sent or the approved references in `brand show`.

- A reference that shows other people or objects lends their traits (hair, smile) to the result even when the prompt assigns the role to one subject. Crop or cut out the wanted subject before attaching it.
- After generating, check each reference for leaks: is its assigned role visible, and did anything else from it come in (a face from a pose reference, the subject of a style reference, colors outside the palette)?
- A front photo does not show the back of an object. Ask for another view, or state the back as a design choice.
- To keep a character the same across scenes, make one anchor image of the character, attach it to every new scene, and repeat the fixed trait list.

## 5. Check after generating (before showing the user)

- No text, letter-like marks, signature, or watermark, including the corners.
- The object is not cut by the frame; the background is the flat color asked for, with none of it on the object.
- Colors stay in the palette; light comes from the stated direction.
- One drawing style across the whole image (see [designer review](../../image-verify/references/designer-review.md)).
- The empty space for text or a logo is really empty.

## 6. Wording rules

- Tie every color, material, and garment to a named part or reference ID ("Image 2's gold trim on the hat brim"), so it does not land on another object.
- Describe a long rigid prop as one straight object with its angle ("one straight sword, pommel to tip on a single line at about 60 degrees, the fist closed around the grip on that line"), and attach a guide drawn by `axis-check --guide` when it must cross a hand or another object. Generators draw the grip and the blade separately and bend them at the hand. Use observed geometry, not invented guide points, and keep protected cards/text outside the prop silhouette. Apply this only to intended straight parts; a bow, curved blade, or angled gun grip must retain its design.
- Plain words beat jargon; heavy art vocabulary did not improve results.
- Photoreal: write "photorealistic" or "real photograph". Camera specs (lens, aperture) only hint at the look.
- People and pose: state "full body visible, feet included", the gaze ("looking down at the cup, not at the camera"), the hand action ("hands naturally gripping the handle"), and the scale relative to nearby objects.
- "Premium" needs visible choices: material, light direction, finish. Never combine conflicting finishes ("casual phone photo" with "flawless studio lighting"). Premium is not beige or gold.
- Transparency: write "isolated on a fully transparent background, no solid backdrop, checkerboard, scenery or shadow". Output PNG or WebP only (JPEG has no alpha). Repeat "preserve the transparent background" in every later edit, and check alpha at hair, glass, and shadow.
- Numbers in a prompt are approximate: a requested 80% scale came out near 70%, and a chart of 90/50/40/20 came out 87.1/49.8/39.2/20.9. When values must be exact, draw them with a chart or vector tool.
- Section headings inside a long prompt kept callout leader lines outside the drawing in 2 of 2 runs, against 0 of 2 for prose (weak evidence, 4 samples).
- Put compatible changes in one call; make fragile or hard-to-diagnose changes one at a time.
- After two failed tries at the same problem, change the method (a sketch, a layer, typesetting, a mask) instead of stronger adjectives. Asking harder for "transparent" still returned a painted checkerboard. When a result misses, find the cause in the [mismatch table](../../image-inspect/references/diagnosis.md#when-a-generated-result-misses-the-request) before rewriting the prompt.

