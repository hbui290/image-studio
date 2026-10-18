# Prompt blocks

Read by [image-create](../SKILL.md) when writing a generation prompt. A prompt built from fixed blocks gives stable results across images and turns, so the user's style does not drift from one asset to the next.

## 1. Style block (same text at the start of every prompt in a job)

Fill it once per brand from the user's taste notes and confirmed preferences, then paste it unchanged:

```text
Style: <medium, e.g. polished 2D hand-painted game art / flat vector / product photo>, <view, e.g. three-quarter top-down>,
<rendering, e.g. soft painterly shading, clean readable silhouettes, not a 3D render>. Mood: <mood>.
Use only this palette: <name #HEX (role)>, <name #HEX (role)>, ...
Lighting: <direction and color of key and rim light>.
No text, letters, numbers, logos, watermarks or signatures<, no people / animals if not wanted>.
```

Use measured values (hex colors, light direction, view angle), not adjectives alone. Never write "in the style of <another artist, game, or company>".

## 2. The item (one item per image)

Describe one asset per image: subject, shape, proportions or aspect ratio, what must be empty (space for a title or logo added later). Generators write text and logos badly: leave that space empty in the image and add exact text or the user's logo file afterwards.

## 3. Background rule (end of the prompt, by asset type)

| Asset | Add |
|---|---|
| Object or ornament to cut out | `Isolated on a perfectly flat solid pure magenta (#FF00FF) background, no gradient, no shadow on the background, crisp edges, generous empty margin. Do not use magenta or pink anywhere in the object.` |
| Glow, light, or particle effect | `On a pure black (#000000) background; the effect fades smoothly into black. Nothing else in the image.` |
| Full scene or background | No background rule; say what stays empty and where. |

Magenta separates cleanly from dark or navy subjects where black does not. Key it out with [ImageMagick](https://imagemagick.org) `magick in.png -fuzz 15% -transparent '#FF00FF' cutout.png` (or rembg), then clean any pink fringe with [cutout edges](../../image-enhance/references/cutouts.md#cutout-edges).

## 4. References

Attach the actual files and give each one a role: `Image 1 is the approved style reference: match its line weight, shading, and palette exactly. Image 2 fixes the product shape.` Use only files the user supplied or approved.

## 5. Check after generating (before showing the user)

- No text, letter-like marks, signature, or watermark, including the corners.
- The object is not cut by the frame; the background is the flat color asked for, with none of it on the object.
- Colors stay in the palette; light comes from the stated direction.
- One drawing style across the whole image (see [designer review](../../image-verify/references/designer-review.md)).
- The empty space for text or a logo is really empty.
