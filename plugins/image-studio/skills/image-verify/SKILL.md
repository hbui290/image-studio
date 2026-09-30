---
name: image-verify
description: Review an image candidate against its source, references, requested changes, and delivery requirements without editing it. Use for independent QA, candidate comparison, or final acceptance checks.
---

# Image verification

Receive the clean source, candidate, approved references, required criteria, target display size, and final acceptance mask if used. Inspect the image itself; prompts and file names are not visual evidence. Keep source and candidate names neutral when comparing alternatives, and do not inherit an editor's preferred verdict as a conclusion.

Check each required change and protected property exactly once with `pass`, `fail`, or `uncertain` plus visible evidence. A missing object prevents its dependent shape or color from passing. Inspect native pixels, neighboring seams, whole composition at delivery size, and decoded file properties. When exact preservation is required, compare source and uncompressed composite outside the final mask numerically; visual review cannot establish pixel identity. Do not certify hidden layers, an exact font, or model identity from pixels.

Read [review-loop.md](references/review-loop.md) for criterion coverage, bounded repairs, and handoff. For local repairs with repeated rounds or a final acceptance mask, [candidate-audit.md](references/candidate-audit.md) describes an optional script that checks file properties, source-coordinate targets, exact decoded pixels outside the mask, review coverage, and the next action. It does not inspect visual meaning or edit pixels. When the editing agent should not grade its own work, have the `image-reviewer` agent (Claude Code) or the image-loop Codex reviewer write the review; the audit accepts either output directly and writes a coordinate-based `repair-prompt.txt` for a repair decision. A required failure rejects the candidate; unresolved required evidence holds it for stronger inspection. Rank aesthetics only among candidates that passed hard checks. Report whether this review was independent or by the editor, what actually ran, and what remains unverified. Do not edit the candidate during a review-only task.
