# Reviewer setup and limitations

## Requirements

`review.py` takes exactly one reviewer: `--model <vision model>` calls Codex; `--report report.json` uses a report already written by the Claude Code `image-reviewer` agent or a person and makes no model call.

- An image-enabled host agent/tool for generation and editing. The review script does not generate images.
- Python 3, Pillow, and jsonschema. Examples use `uv run --with pillow --with jsonschema python ...`; a virtual environment with those packages also works.
- For `--model`: an authenticated Codex CLI and an explicit reviewer model that accepts images on **your configured route**. Verify with an actual image review. A model appearing in a catalog is not proof that a given account/backend can execute it.

Keep the existing CLI provider configuration. The adapter uses it without editing it. It requests a read-only, ephemeral execution and instructs the reviewer to use only the attached images and brief. User-installed CLI skills/configuration may add context and usage; this is not a hermetically isolated inference call.

Pass a vision model your Codex account can actually run; there is no automatic model fallback. The live examples record the models used when they were produced.

If the reviewer requires authentication, use the host's normal login process. Never paste credentials into a prompt, brief, repository, or report. The adapter does not copy credentials or write global configuration. Existing account usage is consumed; no dollar savings are inferred from the model name.

## Run one round

```bash
python3 <skills>/image-loop/scripts/review.py \
  --brief brief.json --source source.png --candidate candidate.png \
  --out round-0 --model <vision-model>
```

Use `--report report.json` instead of `--model` when the `image-reviewer` agent or a person already wrote the review; both `criteria` and `results` formats are accepted.

For the next round, add `--previous round-0` (the folder, or its `report.json`). The script continues only when that round decided `repair`, and it counts repairs from the round history; `--repairs-used` is an optional cross-check. The original source remains the reference for protected criteria. Never feed the numbered annotation copy as the clean source.

A repository checkout includes a controlled revision test in `examples/product/`: reviewing the unchanged source against the requested revision should identify the missing edits.

## Files

- `report.json`: criterion-by-criterion independent visual review.
- `file-checks.json`: decoded dimensions, format, transparency evidence, and candidate SHA-256.
- `decision.json`: deterministic controller outcome.
- `repair-prompt.txt`: generated only when a repair is warranted.
- `reviewer-prompt.txt`: exact prompt used with attached images.
- `run.json`: requested model, account usage as exposed, elapsed time, image hashes, and retry settings. Dollar cost remains unknown unless independently calculated.
- `.private/`: CLI diagnostics, excluded from publication. These can include local paths and installed skill metadata; do not upload them unreviewed.

The script refuses to overwrite a previous round. Invalid output, missing IDs, duplicate IDs, uncertainty, provider failure, and failed file checks stop acceptance. Limits: at most three repairs by default; repeated identical failure sets stop (`stop_repeated_failure`). The script derives the repair count from the `--previous` round folders, so keep each round in its own folder and retain the best protected candidate.

## What the reviewer can and cannot establish

Use vision for visible content, arrangement, local color appearance, and comparison. Use appropriate file/pixel tools for exact dimensions, alpha, and pixel identity. Use a stronger model or a person for uncertainty. Do not infer hidden layers or exact font families. Review small text and ambiguous arrows at adequate resolution; crops must be associated with the full image and original coordinates.

This protocol is motivated by known [vision limitations](https://developers.openai.com/api/docs/guides/images-vision#limitations). Prompting follows [OpenAI's image prompting guide](https://developers.openai.com/api/docs/guides/image-prompting). Image tools may hide their underlying generator model; record the tool name and leave unexposed model identifiers unknown.
