# Case: a blurry AI tavern hero made sharp enough to ship

A real website hero, anonymized. The first generated image was a 1024×576 anime tavern scene with about ten characters, two animal companions, and a crowded background. On a desktop hero it looked soft; up close, faces were tiny and many props were melted. This is the order of work that produced an accepted 3840×2160 result, including the attempts that were thrown away.

## 1. Diagnose before touching pixels

- Rendered page at 1280×720 and 390×844, plus the file at 100%. CSS had no blur filter; a dark overlay reduced contrast; the real problem was missing detail in tiny faces.
- Rejected early: a whole-frame regeneration (it changed expressions) and a sharpen-only pass (nothing visibly improved). Lesson: when defects are local, do not regenerate the whole scene.

## 2. Whole-image enhancement (image-enhance)

```bash
realesrgan-ncnn-vulkan -i hero-4k.webp -o hero-2x.png -s 2 -n realesr-animevideov3 -m models
magick hero-2x.png -filter Lanczos -resize 3840x2160! -unsharp 0x0.55+0.5+0.015 -strip -quality 94 hero-restored-4k.webp
```

Cleaner line continuity, but no recovered identity in faces 20-35 px tall. Always compare eyes, mouths, fingers, and small props with the starting image.

## 3. Local repairs, one region per round (image-repair)

Each round: crop the defect with enough context, send the crop plus the approved character or environment sheet to the host image generator, resize the result to the crop size, accept only a feathered mask of it, composite at the crop offset, and compare the rest.

| Round | Crop (w×h+x+y) | Accepted | Rejected first, and why |
| --- | --- | --- | --- |
| Fireplace, lantern, mantel | 1040×1040+2800+0 | Continuous stone courses, four-sided lantern | — |
| Balcony, railing, city | 1100×1100+0+0 | Even posts, coherent joints | — |
| Standing figure at the edge removed | 1024×1536+2816+400 | Wall and floor rebuilt, seated figure kept | Had to be told apart from a similar seated character |
| Two animal companions | 1200×700+2050+1380 | Both matched their sheets | First mask cut through one ear and ribbon |
| Bar shelves, table props | 1120×790+1520+0, 920×610+2180+1060 | Bottles, mugs, candles | Broad table crop shifted props and left double edges; a tighter crop fixed it. First bar mask left half-bottle ghosts |
| Stairs and balcony posts | 1900×850+0+0, 950×760+800+0 | Open stair entrance, separate rail end | A post still blocked the first steps: rejected |
| Two stray diagonal beams | 1500×1000+0+0 | Two small polygon masks only | — |
| Beer steins | several small crops | Grip matches the handle | A table-steins candidate changed a hand without improving the steins |
| Official brand mark on a map | 760×560+2110+1120 | Clean paper by the generator, mark composited from the official file | A generated emblem was rejected; never let a model redraw a logo |

The prompt pattern that worked, with images attached:

```text
Image 1 is the existing crop and fixes pose, camera angle, and light.
Image 2 is the approved sheet and fixes identity and design.
Redraw only [the named object] in its existing position and size: [specific corrections].
Keep all other people, animals, clothing, props, text, and perspective unchanged. Add no new subject, label, or logo.
```

The masks, not the prompts, protected the neighbors. Typical final check on the uncompressed composite:

```bash
magick compare -metric AE 'previous.png[2340x2160+1500+0]' 'composite.png[2340x2160+1500+0]' null:   # 0 = untouched
```

## 4. A later failure on a different hero, and the rule it produced

A dark painted hero that was already 4K was "repaired" by regenerating a small orb region. The owner saw no difference at display size and asked why the upscaler and segmentation had not been tried. What went wrong: the change was too small to see at 1920 wide, the ellipse mask let the generator redraw a dragon and gold rings inside the orb, and "25% lower pixel error" was reported as if it meant "sharper".

The resulting rules, now enforced by the skills:

- Show a before/after at display size; an invisible change is not an improvement (`compare_display.py`, and the audit holds barely visible changes).
- Try the available upscalers on a crop before deciding they are not needed, and keep only what is visible.
- Protect details inside an edited object with a second mask.
- Report metrics for what they measure.

## 5. Delivery

WebP quality 94 at 3840×2160 (about 2.2 MB), every page reference to the hero updated, page viewed at desktop and 390-wide mobile, build run. The uncompressed composite was the proof of preservation; lossy export changes pixels, so the WebP was only inspected visually.
