---
name: image-loop
description: Generate or edit images with a bounded create-review-repair loop, an independent vision reviewer, explicit preservation checks, and saved evidence. Use for image work that needs iterative checking, or invoke image-loop with a brief or reference image. For exact pixel preservation outside a region, pair it with image-verify's candidate audit.
---

# Image Loop

Convert an image brief into checkable requirements, generate a candidate, review it independently, and repair only failed requirements. Keep useful outputs and an honest record of what passed, failed, or could not be verified.

## Invoke

- Claude Code: `/image-loop [brief]` (shown as `/image-studio:image-loop` when installed as a plugin), or describe the task and let the skill load.
- Codex: `$image-loop [brief]` or select through `/skills` where supported. Do not claim a custom `/image-loop` command is registered on every host.
- Analysis only: a JSON breakdown of an image belongs to the companion `image-reverse-engineer` skill; defect diagnosis belongs to `image-inspect`.
- For multiple inspirations and combination search, route to the companion `image-inspiration` skill. It supports one batch or a bounded human/vision-judged loop and reuses this skill's hard checks.

## Establish the brief

For an image edit, use the companion `image-edit-map` workflow to ask unanswered questions, map sections, and name numbered elements. Respect explicit instructions to skip mapping or edit directly. For new generation, ask only for information essential to the result; do not require a reference image.

Separate subject/content, composition, typography, local color, layer order, grading, medium, lighting, and output requirements. Every reference has a declared role. Record exact text and line breaks. Distinguish protected content from changeable properties. A review must not invent aesthetic requirements absent from the brief.

Write `brief.json` following [the brief contract](references/brief.schema.json). Give every requirement a stable ID and an observable pass condition. Classify it as `requested` or `protected`. File requirements such as dimensions and alpha belong under `file_checks`; visual requirements go under `criteria`. Use visual similarity unless the user explicitly requires exact pixels and the execution path can verify them.

## Execute the loop

1. **Capability check.** Identify an available image generation/editing tool and an independent image-input reviewer. Use host tools under their actual instructions. Never silently substitute an image provider or bypass a tool restriction. A cheaper text model without image input is not a vision reviewer.
2. **Generate.** Save the exact prompt, selected references, tool/model identifiers if exposed, and actual clean output. Do not invent an underlying model name for a tool that hides it. Keep source images untouched. Use a source or last accepted clean candidate, never an annotated map, as the editing input.
3. **Review.** Give an independent reviewer the original clean source when editing, the candidate, and the acceptance criteria. Do not tell it that the image is good, what another reviewer concluded, or what result is expected. Use a configured smaller vision model when it is adequate. A same-agent self-check must be labeled as such if independence is unavailable.
4. **Validate.** Run file checks and enforce complete criterion coverage. Unknown, omitted, malformed, or contradictory results cannot count as passes. Exact font identification, pixel identity, and hidden layer recovery cannot be proven by a vision model alone.
5. **Decide.** If all visual and file checks pass, mark `accepted_by_checks` and deliver for the person's judgment. If any check is uncertain, stop for stronger inspection or a user decision. If there is a concrete failure, emit a narrowly targeted repair prompt and execute it. Re-review the repaired image against the complete original brief, including all protected properties.
6. **Bound retries.** Default to at most three repairs after the initial candidate; the user can lower the limit. Stop if the same set of checks fails in two consecutive reviews (one repair fixed nothing), on a provider failure, or when the agreed budget is exhausted. Never silently retry a failed external call. Preserve the best candidate that passes protected criteria; if none does, retain the source as the safe fallback. Do not overwrite accepted work with an unverified repair.
7. **Deliver.** Show the clean image, changes, check results, remaining uncertainty, and a before/after comparison when useful. Acceptance by a model is not human approval or a measured success rate. Save the candidate, report, file checks, decision, and repair prompt for each round.

Continue through generation and repair during the active task; do not stop at writing a proposed repair when execution is authorized and available. This is an agent-orchestrated loop: the scripts review and decide; the host agent invokes its image tool between rounds.

## Included reviewer adapter

Read [reviewer setup](references/reviewer.md) before running it. `scripts/review.py` uses an authenticated Codex CLI with an explicitly selected vision model and attached local images. It saves structured review results, file checks, and a decision. No OpenAI API key is required for an existing ChatGPT-authenticated CLI. Calls consume the user's account usage.

```bash
python3 <skill-dir>/scripts/review.py \
  --brief brief.json --candidate candidate.png --source source.png \
  --out review-round-0 --model <vision-model>
```

For generation-only briefs, omit `--source`. For repairs, pass `--previous <previous round folder>`; the script counts repairs from the round history and refuses to continue a round that did not decide `repair`. Read `decision.json`; if it says `repair`, execute `repair-prompt.txt` with the appropriate clean image and repeat the review. Stop conditions also apply to manual/alternate reviewer paths. Action names are shared with the audit; see [decisions](../image-verify/references/decisions.md).

Without Codex, ask the `image-reviewer` agent (Claude Code plugin only), a fresh session given [the independent review instructions](../image-verify/references/independent-review.md), or a person to write a report in the same [review contract](references/review.schema.json), then run `scripts/review.py ... --report report.json` instead of `--model`; file checks, coverage, stop rules, and the repair prompt work the same way. For an edit that must keep pixels outside a region exactly, also run the [candidate audit](../image-verify/references/candidate-audit.md) on the same report.

If no adapter fits, use an authorized independent vision tool or reviewer with the same [review contract](references/review.schema.json). Record the actual reviewer and explain the fallback. Do not claim a cheaper-model test occurred unless that model received the images and returned a valid review. Do not claim cost savings without comparable usage/pricing evidence.

## Prompt pattern

Use result → subject/action → composition → medium/style → visible details → constraints for generation. For edits, use source → target/property → requested delta → protected details → success checks. Specify roles for multiple references. Keep prompts as short as the job permits; syntax and length are not quality guarantees.

The public prompt library and example results are in the repository. General prompting principles were informed by the [OpenAI image prompting guide](https://developers.openai.com/api/docs/guides/image-prompting); the numbered controls, review contract, and bounded controller are this package's implementation.

## Running the scripts

In commands, `<skill-dir>` means this skill's folder (the host shows it when the skill loads); run them from your working folder. They need Python 3 with Pillow and jsonschema: `python3 -m pip install pillow jsonschema`, or prefix the command with `uv run --with pillow --with jsonschema`.
