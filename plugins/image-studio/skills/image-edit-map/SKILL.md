---
name: image-edit-map
description: "Plan an edit with the user: ask only needed questions, build a numbered visual map of named elements, and turn the choice into an edit brief with preservation checks. Use when the user wants to change parts of an image and must pick targets. Its reverse-engineering protocol is also used by image-reverse-engineer. Not for a read-only JSON breakdown (image-reverse-engineer), rebuilding or remixing a reference from a full part inventory (image-reconstruction), combining several references into variants (image-inspiration), a new image from a brief (image-create), or defect diagnosis (image-inspect)."
---

# Image edit map

Turn “change that bit” into an addressable edit. Help people see, name, and change an image without needing design vocabulary.

## When to use this skill or a sibling

- **image-edit-map (this skill):** plan an edit of an existing image with a numbered element map, then edit it in place.
- Not for a read-only breakdown with no edit: use [image-reverse-engineer](../image-reverse-engineer/SKILL.md).
- Not for rebuilding or remixing one reference from a full part inventory and a compiled prompt: use [image-reconstruction](../image-reconstruction/SKILL.md).
- Not for combining several references into traceable variants: use [image-inspiration](../image-inspiration/SKILL.md).
- Not for a new image from a brief: use [image-create](../image-create/SKILL.md).
- Not for finding defects: use [image-inspect](../image-inspect/SKILL.md).
- To carry out a local fix that must keep every other pixel: use [image-repair](../image-repair/SKILL.md). This skill plans the edit with a numbered map; image-repair executes a masked local fix, and its [image-verify](../image-verify/SKILL.md) audit proves the rest of the image is unchanged.

## Start here

1. Inspect every supplied image. If no image is available, ask for it; do not invent its contents. Identify which is the edit target and which are references. Read image metadata when possible; do not infer exact dimensions from a resized preview.
2. Ask up to three short, unanswered questions: **What should change? What must stay? Where will you use it?** Offer plain-language choices relevant to the actual image. If the user is unsure, make the map to help them decide. Do not repeat questions already answered in their brief. Ask follow-ups only when they affect the requested result.
3. When targets need a picture to choose from, make a **numbered annotation pass** using [the mapping protocol](references/mapping-and-prompts.md). Prefer drawing badges and boxes on a copy with ImageMagick from source coordinates (`magick src.png -fill none -stroke red -draw "rectangle left,top right,bottom" -font <path to a .ttf> -pointsize 28 -fill red -annotate +x0+y0 "#3" map.png`; ImageMagick needs an explicit font file on many systems, such as `/System/Library/Fonts/Supplemental/Arial.ttf` on macOS). Map boxes are normalized `[x, y, width, height]` fractions; convert them to pixel `left`, `top`, `right`, `bottom` with the [normalized-box to pixel rule](../image-verify/references/candidate-audit.md#contract-and-review) before drawing; use a paid image-generation call for it only when a drawn overlay cannot show the elements. Divide the picture into meaningful sections; point arrows from number badges to individually editable elements. Show the map plus its matching legend before asking the person to select edits. This pass creates a separate review copy, never a redesign of the source.
4. Explain: **“You can say ‘make #3 smaller,’ ‘change #5’s font,’ or ‘keep everything in section B.’”** For multiple pictures, use `A:#3` and `B:#3`.
5. On selection, form an explicit edit instruction with target, property, requested change, and preserved details. Execute once enough information is available. A user's clear edit request authorizes that edit; do not add another approval step unless they asked to review a proposal first.
6. Compare the result with the clean source and the agreed constraints. Deliver a clean image, the actual dimensions, and a brief account of changes and any remaining mismatch.

Honor “just do this,” “skip the map,” or an already complete brief. Do not force a questionnaire or annotation round over an explicit direct-edit instruction. If the user requests planning or prompts only, provide those without generating images. In reverse-engineer mode, analysis is the requested output; do not automatically begin an edit.

## What the user sees

Present a small control menu beside the map. Use [the control dictionary](references/controls.md) for explanations and relevant follow-up questions.

| Control | Changes |
| --- | --- |
| **Text** | The words, spelling, capitalization, and line breaks |
| **Font / typography** | Letterforms, weight, size, spacing, alignment, and hierarchy |
| **Color** | A specific element's fill, stroke, gradient, or opacity |
| **Layer / depth** | What sits in front, behind, inside, or overlaps something else |
| **Color grading** | The overall tonal and color treatment of a photo or selected region |
| **Picture type** | Photo, illustration, 3D render, diagram, collage, screenshot, and related media |
| **Layout / crop** | Position, size, spacing, framing, and aspect ratio |
| **Lighting / material** | Light direction, shadows, reflections, and surface texture |

Example: “Make the title blue” is a local color change. “Give the photo cooler shadows” is grading. “Put the title behind the person” is layer order. Changing one does not authorize changes to the others.

## Conversational commands

These are instructions recognized **inside this skill**, not automatically installed host slash commands. If the host treats a leading slash as its own command, invoke this skill (`/image-edit-map` in Claude Code or `$image-edit-map` in Codex) and give the command in plain language, such as "map" or "lock A:#3".

| Command | Behavior |
| --- | --- |
| `/map` | Number and name the visible sections/elements; show a separate annotated review image and legend |
| `/inspect A:#3` | Explain that element's editable properties in everyday language |
| `/edit A:#3 ...` | Apply the specified change with all other properties preserved |
| `/lock A:#3` or `/lock A:S1` (a section) | Protect specified elements/regions; clarify visual similarity versus exact pixels if needed. Only elements store locks (`locked_properties`); a section record has no lock field, so `/lock A:S1` adds the locks to every element in that section |
| `/unlock A:#3` | Remove that requested protection without changing the artwork |
| `/spec` | Extract a structured visual specification with [the reverse-engineering protocol](references/reverse-engineer.md); for a JSON-only request outside an edit, [image-reverse-engineer](../image-reverse-engineer/SKILL.md) does the same |
| `/compare` | Compare named versions against the requested edit and protected content |
| `/export` | Resolve dimensions, crop policy, background, and format; verify the saved file |
| `/help` | Show the control menu and two example commands suitable for the current image |

## Preserve intent

- Keep original sources untouched. Give each image a source ID and each edit a version. Use the last accepted **clean** version for subsequent edits; never an annotated review image.
- Keep stable element IDs even if elements move. Retire deleted IDs; do not reuse them. New elements get new IDs. A changed source/layout requires updating the map and its coordinates before executing stale selections.
- Exact wording, capitalization, punctuation, line breaks, diagram labels, node counts, and arrow directions are separate constraints from visual style.
- “Use this reference” requires a role: typography, palette, composition, subject, lighting, or medium. Carry over only the assigned properties. If references conflict, resolve only the conflicting role with the user.
- “Keep that diagram” protects its topology and arrangement. A restyle does not authorize changing relationships or adding/removing nodes. Match the visual structure to the meaning when designing a new diagram: a central identity can radiate outward; a sequence needs directional connections.
- Resolution-only means preserve content and design. Clarify an ambiguous “4K” target when it affects aspect ratio. Never silently stretch, crop, or add content to hit a pixel count.
- “Everything else unchanged” is a constraint to verify, not proof that a generative edit succeeded. Exact pixel preservation requires an appropriate deterministic composition/editing workflow and a pixel comparison. If the available tool cannot provide that, disclose the limit before claiming success.
- Preserve the selected branch/version. If an edit drifts, retry from the accepted clean source rather than accumulating damage through the failed result.

## Tools and evidence

Use the host's image inspection and editing tools according to their live instructions. Prefer its image-generation/editing tool for actual image edits. Do not bypass tool restrictions with scripts or another provider. This skill supplies no API key, model entitlement, native editor, or automatic image renderer.

If image editing is unavailable, provide the map manifest, legend, and prepared annotation/edit prompt, and clearly say the visual map or edit has not been rendered. Do not substitute a text table and claim an annotated image exists. If the user wants deterministic overlays or compositing, use an appropriate editor only when authorized and supported.

Separate visible evidence from estimates. A flat image does not reveal original editable layers, an exact font family, the original prompt, a precise LUT, or hidden/occluded content. Report unknowns instead of presenting guesses as recovered facts.

Before delivery, use [the verification checklist](references/verification.md). When returning JSON, conform to [the schema](references/image-spec.schema.json). Source-specific identifiers, coordinates, and values must come from the current input, not the example file.

## Optional visual preset

If the person explicitly asks for a technical-editorial look, offer a dark or paper-light background, mostly white or black content, restrained blue emphasis, readable typography, and meaningful diagram connections. Confirm the chosen direction; never apply this palette, a fixed canvas size, a brand, or a layout to someone's image by default.

This workflow combines a numbered editing interface with lessons from targeted image revisions. General prompting guidance also informed it: [OpenAI image prompting](https://developers.openai.com/api/docs/guides/image-prompting). Verify current tool capabilities separately; this skill deliberately does not freeze model names or API settings.

## Running the scripts

In commands, `<skills>` means the folder that holds the Image Studio skill folders, which is this skill's parent folder (the host shows the skill's path when it loads); run commands from your working folder. They need Python 3 with jsonschema (and Pillow for `--image`): prefix the command with `uv run --with pillow --with jsonschema` ([uv](https://docs.astral.sh/uv/)), or install them with `python3 -m pip install pillow jsonschema`.

Validate a saved map manifest or spec:

```sh
python3 <skills>/image-edit-map/scripts/validate_spec.py image-spec.json --image <source image>
```

`--image` is optional and checks the reported width and height against the decoded file; add `--image-id B` when the spec describes more than one image. Exit codes: `0` passed (prints `PASS: ...`; visual accuracy is not checked), `1` the spec is invalid or the dimensions do not match (one problem per line), `2` a file is missing or unreadable, the JSON cannot be parsed, or a dependency is missing.
