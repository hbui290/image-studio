# Edit-map workflow details

Read by [image-edit-map](../SKILL.md) only when the condition named there holds.

## What the user sees

Present a small control menu beside the map. Use [the control dictionary](controls.md) for explanations and relevant follow-up questions.

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

These are instructions recognized **inside this skill**, not automatically installed host slash commands. If the host treats a leading slash as its own command, invoke this skill (`/image-edit-map` in Claude Code, shown with the plugin's prefix in a plugin install, or `$image-edit-map` in Codex) and give the command in plain language, such as "map" or "lock A:#3".

| Command | Behavior |
| --- | --- |
| `/map` | Number and name the visible sections/elements; show a separate annotated review image and legend |
| `/inspect A:#3` | Explain that element's editable properties in everyday language |
| `/edit A:#3 ...` | Apply the specified change with all other properties preserved |
| `/lock A:#3` or `/lock A:S1` (a section) | Protect specified elements/regions; clarify visual similarity versus exact pixels if needed. Only elements store locks (`locked_properties`); a section record has no lock field, so `/lock A:S1` adds the locks to every element in that section |
| `/unlock A:#3` | Remove that requested protection without changing the artwork |
| `/spec` | Extract a structured visual specification with [the reverse-engineering protocol](reverse-engineer.md); for a JSON-only request outside an edit, [image-reverse-engineer](../../image-reverse-engineer/SKILL.md) does the same |
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

Use the host's image inspection and editing tools according to their live instructions. Prefer its image-generation/editing tool (`image_gen.imagegen` in Codex; Claude Code has none built in, so hand back the prepared prompt) for actual image edits. Do not bypass tool restrictions with scripts or another provider. This skill supplies no API key, model entitlement, native editor, or automatic image renderer.

If image editing is unavailable, provide the map manifest, legend, and prepared annotation/edit prompt, and clearly say the visual map or edit has not been rendered. Do not substitute a text table and claim an annotated image exists. If the user wants deterministic overlays or compositing, use an appropriate editor only when authorized and supported.

Separate visible evidence from estimates. A flat image does not reveal original editable layers, an exact font family, the original prompt, a precise LUT, or hidden/occluded content. Report unknowns instead of presenting guesses as recovered facts.

Before delivery, use [the verification checklist](verification.md). When returning JSON, conform to [the schema](image-spec.schema.json). Source-specific identifiers, coordinates, and values must come from the current input, not the example file.

The validate command and its exit codes are in [SKILL.md](../SKILL.md).
