# Candidate audit for local image repairs

This optional helper checks a saved candidate against **this plugin's** scene contract. It never creates an image, detects objects, or substitutes a visual review. Use it when an edit has protected neighbors, a final acceptance mask, or several repair rounds. For a simple crop, inspect the file directly.

## What is different here

The contract joins stable object IDs to **source-pixel** boxes and labels each requirement as a requested `change` or protected `keep`. A reviewer supplies visible observations. The helper decodes the images, measures changed pixels per object, checks dimensions and format, and can reject every changed pixel outside the final acceptance mask. It rejects a claimed passed change when no pixel changed inside its target box, and holds a passed `keep` check whose target box changed more pixels than the reviewer acknowledged. The resulting decision names the checks to repair and requires all checks to be inspected again.

The helper uses Python 3 and [Pillow](https://pillow.readthedocs.io/en/stable/installation/basic-installation.html). Install Pillow only if choosing this helper. For example, create a task-local virtual environment with `python3 -m venv .venv`, activate it (`source .venv/bin/activate` on POSIX or `.venv\Scripts\Activate.ps1` in PowerShell), then run `python -m pip install pillow` and use that environment's `python` for the command below. There is no schema library, Codex CLI, account, or model requirement. The plugin does not install Pillow automatically. A human or available image-capable tool must actually inspect the source and candidate before writing the review JSON; script output alone cannot establish anatomy, object identity, perspective, text accuracy, or artistic quality.

## Contract and review

Save a `contract.json` tied to the **original clean source**, not a screenshot or annotated map:

```json
{
  "version": 1,
  "mode": "repair",
  "intent": "Fix one tavern mug while preserving the nearby hand",
  "canvas": {"width": 2048, "height": 1024, "format": "PNG"},
  "targets": [
    {"id": "A:#7", "name": "held mug", "bbox": [410, 220, 180, 210]},
    {"id": "A:#8", "name": "adjacent hand", "bbox": [360, 250, 100, 130]}
  ],
  "checks": [
    {"id": "C1", "target_id": "A:#7", "kind": "change", "requirement": "One continuous handle joins the mug"},
    {"id": "K1", "target_id": "A:#8", "kind": "keep", "requirement": "Finger count and overlap match the source"}
  ],
  "pixel_lock_outside_mask": true,
  "max_repairs": 3
}
```

Each box is `[x, y, width, height]` in source pixels. The **final acceptance mask** is the same size as the image: every nonzero pixel, including a feathered edge, permits candidate pixels; pure black locks source pixels, and so does any fully transparent pixel of an RGBA mask. It is distinct from a generator's input mask. Write `canvas.format` as the uppercase name Pillow decodes, such as `PNG`, `JPEG`, or `WEBP`. When `pixel_lock_outside_mask` is false or omitted, omit `--mask`; the script will not claim exact preservation outside a region. For new artwork use `mode: "create"`, omit `--source` and the pixel lock, use only `change` checks (a `keep` check needs a source to compare with), and map targets on the output canvas.

Boxes from a numbered map are often normalized `[x, y, width, height]` fractions of the image. Convert them to source pixels before writing the contract: `x_px = round(x * source_width)`, `y_px = round(y * source_height)`, `width_px = round(width * source_width)`, `height_px = round(height * source_height)`, then clamp to the canvas.

After looking at the actual images, save `review.json` with one result for every check:

```json
{
  "reviewer": "human visual review at native pixels and delivery size",
  "results": [
    {"id": "C1", "status": "fail", "evidence": "The upper handle stops before the mug rim"},
    {"id": "K1", "status": "pass", "evidence": "The visible fingers and overlap match the source"}
  ]
}
```

Use `pass`, `fail`, or `uncertain`. Evidence must describe what was seen or why it could not be resolved. The script validates IDs and coverage, but cannot prove the reviewer's visual claim. Keep the reviewer independent of the editor when the image warrants it. An optional `suggested_fix` text on a result is copied into the repair prompt.

## Who writes the review

Any of these produce a review the audit accepts unchanged:

| Reviewer | How | Cost |
| --- | --- | --- |
| A person | Write `review.json` as above | None |
| Fresh reviewer session (any host) | Give it [independent-review.md](independent-review.md) and the file paths; it writes the `criteria` format | Session usage |
| Claude Code `image-reviewer` agent (plugin install only) | Ask the agent to review `source.png`, `candidate.png` against `contract.json` and write `review.json`; it writes the `criteria` format | Session usage |
| Codex vision model | `python3 <skill-dir>/scripts/contract_to_brief.py contract.json --out brief.json`, then run the [image-loop reviewer](../../image-loop/references/reviewer.md) with `--brief brief.json --model <vision model>`; pass its `report.json` here as `--review` | Codex account usage |

The `criteria` format is `{"criteria": [{"id", "status", "evidence", "suggested_fix"}], "summary": "..."}`. The model's verdict never overrides the pixel checks: a vision `pass` with a changed pixel outside the mask is still `reject_technical`.

A protected box often overlaps the editable area; in the example above, the hand box overlaps the mug. When `decision.json` lists `changed_keep_pixels` for a passed `keep` check, inspect those pixels. If the change is a permitted consequence such as a contact shadow, add `"acknowledged_changed_pixels": <count>` to that result and describe the change in its evidence. A later candidate that changes more pixels in that box is held again.

## Run and interpret

```bash
python3 <skill-dir>/scripts/audit_candidate.py \
  --contract contract.json --source source.png --candidate candidate.png \
  --mask final-acceptance-mask.png --review review.json --out round-0
```

Omit `--mask` when the contract does not require a pixel lock. For the next repair round, pass `--previous round-0` and a new output folder. The helper checks that the previous round used the same contract and original source hashes and decided `repair`, and it counts repairs from that history (`--repairs-used` is only an optional cross-check). Repair from the last accepted clean source or candidate, not an annotated review copy or a chain of rejected outputs.

Read `evidence.json` for file hashes, decoded dimensions, changed-pixel counts by target, and any pixels changed outside the mask. Read `decision.json`; its actions, their order, and the next step for each are in [decisions.md](decisions.md), shared with the image-loop reviewer. A `repair` decision lists failed `ids` and `protected_failed`, writes `repair-prompt.txt` naming each failed and protected target by its source-pixel box, and requires another complete review. `accepted_by_checks` means the **specified** checks passed; it is not user approval. Pixel equality is checked on decoded pixels after applying EXIF orientation, not by comparing file bytes: 8-bit images as RGBA, and 16-bit or floating-point grayscale at full precision. A change of bit depth between source and candidate is a technical failure. Pillow decodes 16-bit-per-channel color PNGs as 8-bit, so for those files the comparison is 8-bit. It does not certify color-profile appearance or hidden layers. A pixel that is fully transparent in both images counts as unchanged even when its hidden color values differ.

In a repository checkout, `python3 -m unittest discover -s tests` tests these helpers.

## Origin of the approach

The bounded review idea was informed by [Image Loop](../../image-loop/SKILL.md) and stable IDs by [Image Edit Map](../../image-edit-map/SKILL.md). This helper and contract were written for the local mask/composite workflow of the earlier image-processing skill; Image Studio connects it to the Image Loop reviewer through `contract_to_brief.py` and the shared `criteria` review format.
