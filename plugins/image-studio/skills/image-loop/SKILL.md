---
name: image-loop
description: "Iterative generation, review loop, multi-round repair, image loop, brief to image: run a bounded create-review-repair loop with independent vision review, explicit preservation checks, and saved evidence. Not for upscaling (image-enhance) or single-region fixes (image-repair)."
---

# Image loop

Run a bounded create-review-repair loop with independent review and saved evidence.

Routing: For single-pass generation use [image-create](../image-create/SKILL.md); for reference mixing use [image-inspiration](../image-inspiration/SKILL.md); for local fixes use [image-repair](../image-repair/SKILL.md); for whole-image enhancement use [image-enhance](../image-enhance/SKILL.md); for read-only breakdown use [image-reverse-engineer](../image-reverse-engineer/SKILL.md); to inspect defects use [image-inspect](../image-inspect/SKILL.md).

Run scripts; do not read their source - use `--help` for usage.

## Operational checklist

0. **Memory:** If not in context, run `python3 <skills>/image-verify/scripts/studio_state.py brief` (no store: `taste list` and `lesson list` instead) (see [using the store in a skill](../image-verify/references/project-memory.md#using-the-store-in-a-skill)).
1. **Brief:** Write `brief.json` with stable IDs, observable criteria (`requested` vs `protected`), and `file_checks` (dimensions, format, alpha). Read [brief.schema.json](references/brief.schema.json) only when writing the structured brief. Use [image-edit-map](../image-edit-map/SKILL.md) if edit targets are unclear.
2. **Generate:** Run host image generator under its instructions (Codex: `image_gen.imagegen`; Claude Code has none built in: use a configured image tool or hand back the prompt); never silently substitute a provider or retry a failed external call. A text-only model is not a vision reviewer. Read [prompts-and-invoke.md](references/prompts-and-invoke.md) only when writing a prompt or invoking from another host. Keep clean source untouched; edit from clean source or accepted candidate, never annotated review maps.
3. **Review:** Independent review with attached images, brief, and clean source; label a same-agent self-check as such and, for the first candidate and before delivery, run it as a [designer review](../image-verify/references/designer-review.md). Use `--model` for Codex (add `--crop` with 100% crops of small text and protected details: attached full images are shrunk) or `--report` for an existing report (in Claude Code, the `image-reviewer` agent through the Agent tool; or a person):
   ```bash
   python3 <skills>/image-loop/scripts/review.py \
     --brief brief.json --candidate candidate.png --source source.png \
     --out review-round-0 --model <vision-model>
   ```
   Run: `uv run --with pillow --with jsonschema python3 <skills>/image-loop/scripts/review.py ...` ([uv](https://docs.astral.sh/uv/)) (fallback: `python3 -m pip install pillow jsonschema`). Read [reviewer.md](references/reviewer.md) only when configuring flags (`--timeout`, `--source`) or models. Read [review.schema.json](references/review.schema.json) only when formatting review reports. Read [independent-review.md](../image-verify/references/independent-review.md) only when setting up independent review. Read [candidate-audit.md](../image-verify/references/candidate-audit.md) only when exact pixel preservation is required.
4. **Decide:** Follow deterministic controller decision in `decision.json`. Actions: `accepted_by_checks`, `repair`, `hold_for_inspection` (uncertainty), `stop_budget` (budget reached), `stop_repeated_failure` (2 consecutive identical failure sets), `stop_provider` (timeout/failure), `stop_invalid_review` (missing/duplicate/extra IDs), `reject_technical` (file check failure). Read [decisions.md](../image-verify/references/decisions.md) only when interpreting actions or stop rules.
5. **Repair:** Default at most 3 repairs (`--max-repairs`). Keep the best candidate that passes protected criteria (else the source); never overwrite accepted work with an unverified repair. If `decision.json` says `repair`, execute `repair-prompt.txt` on clean image. For next round pass `--previous <round folder>` (counts repairs; optional cross-check `--repairs-used`). When a changed method works after two failures, record it with `lesson add ... --worked` ([taste and lessons](../image-verify/references/project-memory.md#taste-and-lessons)).
6. **Gate before claiming done:** In a project with a store, run `gate --deliverable` once before claiming done; follow [using the store in a skill](../image-verify/references/project-memory.md#using-the-store-in-a-skill).
7. **Deliver:** Present clean image, changes, check results, and evidence. Outputs in round folder: `report.json`, `file-checks.json`, `decision.json`, `repair-prompt.txt`, `reviewer-prompt.txt`, `run.json`, `.private/`. Exit codes: 0 when a usable decision was written (including `reject_technical`); 2 on bad arguments, unreadable images or an animated `--source`, `stop_invalid_review`, or `stop_provider` (both written to `decision.json`). Read `decision.json`, not the exit code.
