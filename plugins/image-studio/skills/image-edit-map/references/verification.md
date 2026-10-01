# Verification and delivery

## Before an edit

- Identify the correct clean source and current version. Check that its map still matches.
- Translate selections into target names, coordinates, requested properties, and locks.
- Resolve incompatible requirements, e.g. global warming versus exact logo colors, a larger title versus a fixed text box, or a new aspect ratio versus no crop/padding.
- If no conflict or missing information prevents the requested edit, proceed without a second permission loop.

## After an edit

Inspect both the full image and relevant detail crops, then compare with the clean source:

1. Requested change: is the selected property actually different in the requested way?
2. Preservation: did non-target content, layout, geometry, labels, or identifying details drift?
3. Typography: spelling, punctuation, capitalization, exact breaks, clarity, and glyph confusions such as `AI` versus `Al`.
4. Diagrams: count nodes; follow arrows end to end; check branches, return paths, labels, and meaning. A pretty image with different connections fails a restyle request.
5. Compositing: edges, halos, contact shadows, occlusion, perspective, and unintended new objects.
6. Output: read actual width/height and format; verify requested alpha from the decoded file. A checkerboard painting is not transparency. File extension alone is not format verification.
7. Viewing context: inspect at actual use size, especially thumbnails and mobile crops. Check key text and relationships remain readable.
8. Clean delivery: no numbered badges, annotation arrows, crop guides, or review labels unless explicitly requested in the final artwork.

Compare protected regions visually for ordinary edits. If exact pixels are required, compare decoded values in aligned source coordinates without silently resizing one image to manufacture a match. If the canvas changes, define the coordinate transform first. Generative similarity is not pixel equality. Record a check as passed, failed, or not performed; do not imply all checks ran automatically.

A mask constrains a tool's edit area only to the extent supported by that tool. Do not promise hard preservation based solely on a mask or the words “unchanged.” When deterministic preservation is needed but not available, provide the concrete edit specification and explain the execution limit.

## Resize/export decisions

- Distinguish resampling existing pixels from generative reconstruction or added detail.
- Preserve the canvas for scoped edits unless a size change was requested.
- For a changed aspect ratio, establish crop, pad, outpaint, or explicitly requested stretch. Respect an exact user-supplied width/height over a historical preset.
- “4K” alone is ambiguous for a wide banner: ask for an exact canvas or whether the user means a 3840-pixel long edge. Do not call every 3840-wide image a standard 3840×2160 canvas.
- Verify relevant color profile, print dimensions/bleed, compression, and file size only when requested or required by the output brief.

## Delivery

Show the clean result and link/save the file when supported. Summarize what changed and what was verified. Mention only material failures or unperformed checks. Keep the map, source, edit versions, and JSON separately named. Provide updated IDs/coordinates if the user plans to continue editing.
