---
name: image-create
description: Create a new raster image in one generation pass from a brief and approved references, giving each reference a declared role such as identity, product, layout, material, light, or style. Use when asked to "create an image", "generate hero art", "make an illustration", "make a product scene", or "generate from these references". Not for review-and-repair rounds (image-loop), mixing many inspirations into directions (image-inspiration), fixing one region of an existing image (image-repair), or sharpening and upscaling (image-enhance).
---

# Image creation

Generate a new image with controlled composition, identity, and delivery size. This skill covers one generation pass (or a few candidates) and records what was asked and what came out. It does not run repair rounds.

## When to use this skill or a sibling

- **image-create (this skill):** a new image from a brief, where each attached reference has a role. One pass, then hand the result to a check.
- **[image-loop](../image-loop/SKILL.md):** generate or regenerate a whole image, then review it independently and repair failed checks up to a repair limit.
- **[image-inspiration](../image-inspiration/SKILL.md):** many inspiration images or notes that should be broken into ingredients and mixed into several directions.
- **[image-repair](../image-repair/SKILL.md):** fix one region of an existing accepted image while the rest stays unchanged.

## Requirements

- An image generation tool available to the agent. Use it under its own instructions; never substitute another provider without saying so.
- Optional, for checking: the `image-reviewer` agent (Claude Code plugin only), [image-verify](../image-verify/SKILL.md), or the [image-loop](../image-loop/SKILL.md) reviewer script.

## Steps

1. **Write the brief.** Define the image's job, canvas size, medium, subject, composition, copy space, output format, and the checks it must pass. If no source image exists, describe the brief as the user's intent, not as a reconstructed original.
2. **Assign reference roles.** Give each attached reference one specific role: identity, product truth, layout, material, light, or style. Name exclusions and resolve conflicts. A style image cannot override an approved logo or product shape.
3. **Write the prompt.** Use result, then subject and action, composition, medium and style, visible details, and constraints. State each reference's role in the prompt.
4. **Attach the references.** Attach the actual selected images; a file path written in the prompt does not attach an image. For hard placement or pose, attach a simple geometry sketch with an explicit legend when the tool accepts one.
5. **Generate.** Produce one candidate, or a small set when the user wants options. Keep source and reference files unchanged.
6. **Compare candidates.** View all candidates at the same target size. Check required content, identity, geometry, crop, and file properties before choosing by taste. A larger pixel count or a pleasing first impression is not evidence of correct small details. Reject variants that change a protected reference.
7. **Hand off for checking** (see below) when the image must meet stated requirements.

## What to write down

Save these next to the candidates:

- The exact prompt sent to the tool.
- The tool name and the model name if the tool exposes it. Do not invent a hidden model name.
- Each reference file and its role.
- The clean output files, without annotations.

Do not present generated text or logos as exact. Composite approved source art over the result, or use editable page text when the text does not need to live inside the scene.

## Outputs

- One or more clean candidate images at the requested size and format.
- The record above, and which candidate was chosen and why.

## Stop conditions

- Stop after the planned candidates are generated and compared. Further rounds of fixes belong to [image-loop](../image-loop/SKILL.md).
- Stop and ask when references conflict in a way the brief does not resolve, or when no image generation tool is available.
- Stop on a tool failure; do not retry silently.

## Hand the result to a check

- **One review without repairs:** use [image-verify](../image-verify/SKILL.md). Have the `image-reviewer` agent, a fresh session, or a person review the candidate against the checks. For new artwork, the [candidate audit](../image-verify/references/candidate-audit.md) accepts `mode: "create"` with no `--source`.
- **Review and repair rounds:** write `brief.json` and continue in [image-loop](../image-loop/SKILL.md), omitting `--source` for a generation-only brief.
- Read [review-loop.md](../image-verify/references/review-loop.md) for multiple candidates or repair rounds.
