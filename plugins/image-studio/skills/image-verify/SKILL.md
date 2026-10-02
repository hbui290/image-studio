---
name: image-verify
description: Review an image candidate against its source, references, requested changes, and delivery requirements without editing it. Use for independent QA, candidate comparison, or final acceptance checks, and to audit that pixels outside a mask did not change. Not for generating images (image-create, image-loop), editing or repairing pixels (image-repair), or diagnosing defects in an image with no stated requirements (image-inspect).
---

# Image verification

Check a candidate against stated requirements and report what passed, failed, or could not be verified. Do not edit the candidate during a review-only task.

## Not for

- Generating a new image: use [image-create](../image-create/SKILL.md) or [image-loop](../image-loop/SKILL.md).
- Changing pixels to fix a failure: use [image-repair](../image-repair/SKILL.md), then come back here.
- Finding defects when no requirements exist yet: use [image-inspect](../image-inspect/SKILL.md).

## Steps

1. **Collect inputs.** The clean source, the candidate, approved references, required criteria, target display size, and the final acceptance mask if one is used. Inspect the image itself; prompts and file names are not visual evidence. Keep source and candidate names neutral when comparing alternatives, and do not inherit an editor's preferred verdict as a conclusion.
2. **Choose the reviewer.** When the editing agent should not grade its own work, have an independent reviewer write the review: the `image-reviewer` agent (Claude Code plugin), a fresh session given [independent-review.md](references/independent-review.md) (any host), the [image-loop](../image-loop/SKILL.md) Codex reviewer, or a person. Codex has no `image-reviewer` agent: start a separate agent with independent-review.md where the host allows it; otherwise the editor's own review must say so in its `review.json` and in the report to the user.
3. **Review each check once.** Give every required change and protected property exactly one `pass`, `fail`, or `uncertain` with visible evidence. A missing object prevents its dependent shape or color from passing. Inspect native pixels, neighboring seams, the whole composition at delivery size, and decoded file properties. Read [acceptance.md](references/acceptance.md) for the identity, craft, composition, file, and evidence checks.
4. **Audit pixels when exact preservation is required.** Visual review cannot establish pixel identity; compare source and uncompressed candidate outside the final mask numerically with the audit below. Do not certify hidden layers, an exact font, or model identity from pixels.
5. **Decide.** A required failure rejects the candidate; unresolved required evidence holds it for stronger inspection. Rank aesthetics only among candidates that passed hard checks. Decision names and their order are in [decisions.md](references/decisions.md); criterion coverage, bounded repairs, and handoff are in [review-loop.md](references/review-loop.md).
6. **Report** whether the review was independent or by the editor, what actually ran, and what remains unverified.

## Candidate audit

For local repairs with repeated rounds or a final acceptance mask, [candidate-audit.md](references/candidate-audit.md) describes `audit_candidate.py`. It checks file properties, source-coordinate targets, exact decoded pixels outside the mask, review coverage, and the next action. It does not inspect visual meaning or edit pixels. It accepts the `results` or `criteria` review format directly.

```bash
python3 <skills>/image-verify/scripts/audit_candidate.py \
  --contract contract.json --source source.png --candidate candidate.png \
  --mask final-acceptance-mask.png --review review.json --out round-0
```

Omit `--mask` when the contract does not set `pixel_lock_outside_mask`, and omit `--source` for a `create` contract. For the next round add `--previous round-0` and a new `--out` folder; `--repairs-used` is an optional cross-check. To have the image-loop Codex reviewer write the review, convert the contract with `python3 <skills>/image-verify/scripts/contract_to_brief.py contract.json --out brief.json`.

**Outputs** in the `--out` folder: `evidence.json` (hashes, decoded dimensions, changed pixels by target and outside the mask), `decision.json`, a copy of `review.json`, and `repair-prompt.txt` with coordinate-based instructions when the decision is `repair`.

**Exit codes:** 0 means a decision was written, whatever its action; read `decision.json`. 2 means bad input (missing file, invalid contract or review, mismatched round history, existing `--out` folder) and nothing was written.

## Stop conditions

- Stop after every check has one verdict and the decision is reported. Do not start repairs in a review-only task.
- Stop on `hold_for_inspection` and ask for closer inspection or a user decision.
- Stop on `reject_technical`, `stop_budget`, or `stop_repeated_failure` and report the next step from [decisions.md](references/decisions.md).

## Running the scripts

In commands, `<skills>` means the folder that holds the Image Studio skill folders, which is this skill's parent folder (the host shows the skill's path when it loads); run commands from your working folder. `audit_candidate.py` needs Python 3.9+ with Pillow: run it as `uv run --with pillow python3 <skills>/image-verify/scripts/audit_candidate.py ...` ([uv](https://docs.astral.sh/uv/)), or install Pillow once with `python3 -m pip install pillow` and use `python3` directly. `contract_to_brief.py` needs only Python 3.9+.
