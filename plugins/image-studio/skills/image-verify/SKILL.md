---
name: image-verify
description: "Verify image, review candidate, QA check, acceptance check, audit pixels: verify candidate against source, references, and contract requirements without editing pixels. Audit masks, enforce stop rules, run store gate, record evidence."
---

# Image verification

Verify candidates against stated requirements and audit preservation without editing pixels.

Routing: To generate new images use [image-create](../image-create/SKILL.md) or [image-loop](../image-loop/SKILL.md); to fix defects use [image-repair](../image-repair/SKILL.md); to diagnose without criteria use [image-inspect](../image-inspect/SKILL.md).

Run scripts; do not read their source - use `--help` for usage.

## Operational checklist

0. **Memory:** If not in context, run `python3 <skills>/image-verify/scripts/studio_state.py brief` (see [using the store in a skill](references/project-memory.md#using-the-store-in-a-skill)).
1. **Reviewer:** Use independent review. Read [independent-review.md](references/independent-review.md) only when setting up reviewer instructions.
2. **Review checks:** Give each check one `pass`, `fail`, or `uncertain` with visible evidence. Read [acceptance.md](references/acceptance.md) only when evaluating craft checks. Read [repair-rules.md](../image-repair/references/repair-rules.md) only when checking logos, packaging text, or transparent exports. Before showing a new or regenerated image, or before delivery, follow [designer-review.md](references/designer-review.md): tiles, edges, grayscale, thumbnail, lineup, problems first.
3. **Candidate audit:** When exact pixel preservation outside a mask is required:
   ```bash
   python3 <skills>/image-verify/scripts/audit_candidate.py \
     --contract contract.json --source source.png --candidate candidate.png \
     --mask final-acceptance-mask.png --review review.json --out round-0
   ```
   `audit_candidate.py` needs Python 3.9+ with Pillow: run as `uv run --with pillow python3 <skills>/image-verify/scripts/audit_candidate.py ...` ([uv](https://docs.astral.sh/uv/)) or install Pillow via `python3 -m pip install pillow`. Read [candidate-audit.md](references/candidate-audit.md) only when configuring audit options.
4. **Decide:** Follow `decision.json` (`accepted_by_checks`, `repair`, `hold_for_inspection`, `reject_technical`, `stop_budget`, `stop_repeated_failure`). Read [decisions.md](references/decisions.md) only when deciding next actions or stop rules.
5. **Gate before claiming done:** In a project with a store, run `gate --deliverable` once before claiming done; follow [using the store in a skill](references/project-memory.md#using-the-store-in-a-skill).
6. **Report:** Say if the review was independent or by the editor. When the gate has not passed, tell the user in plain words what is still wrong (defect IDs only in parentheses). When the user approves or praises a result, record what they liked with `taste add` ([taste and lessons](references/project-memory.md#taste-and-lessons)).
