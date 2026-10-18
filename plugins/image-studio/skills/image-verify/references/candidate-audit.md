# Candidate audit for local image repairs

This helper audits a candidate against the scene contract without creating images or detecting objects. Use when an edit has protected neighbors, a final acceptance mask, or several repair rounds.

The contract links stable object IDs to source-pixel boxes and labels each check as `change` or `keep`. The helper decodes images, measures changed pixels per object, verifies dimensions and format, and rejects changed pixels outside the final acceptance mask. It rejects a claimed pass for `change` when no pixel changed in its box, and holds a passed `keep` check if changed pixels exceed acknowledged limits.

Run with Python 3.9+ and [Pillow](https://pillow.readthedocs.io/en/stable/installation/basic-installation.html), using [uv](https://docs.astral.sh/uv/) or pip:
```bash
uv run --with pillow python3 <skills>/image-verify/scripts/audit_candidate.py ...
# Fallback: python3 -m pip install pillow
```

## Contract and review

Save `contract.json` tied to the clean source:

```json
{
  "version": 1,
  "mode": "repair",
  "intent": "Fix mug handle while preserving adjacent hand",
  "canvas": {"width": 2048, "height": 1024, "format": "PNG"},
  "targets": [
    {"id": "A:#7", "name": "mug", "bbox": [410, 220, 180, 210]},
    {"id": "A:#8", "name": "hand", "bbox": [360, 250, 100, 130]}
  ],
  "checks": [
    {"id": "C1", "target_id": "A:#7", "kind": "change", "requirement": "Handle joins mug"},
    {"id": "K1", "target_id": "A:#8", "kind": "keep", "requirement": "Fingers match source"}
  ],
  "pixel_lock_outside_mask": true,
  "max_repairs": 3
}
```

- **Canvas & format**: `canvas.format` is uppercase Pillow format (`PNG`, `JPEG`, `WEBP`, `TIFF`). Add `"alpha_required": true` when transparent pixels are required. Animated files are rejected; audit one still frame.
- **Mask**: `final-acceptance-mask.png` matches canvas size. Pure black locks source pixels; nonzero values (including feathered edges) permit candidate pixels. Fully transparent pixels in RGBA masks lock source pixels. Omit `--mask` when `pixel_lock_outside_mask` is false or omitted.
- **Create mode**: In `mode: "create"`, omit `--source` and pixel lock, use only `change` checks, and map targets on the output canvas.
- **Normalized coordinates**: Convert normalized `[x, y, width, height]` to source pixels using the [reconstruction field guide](../../image-reconstruction/references/field-guide.md): `left = floor(x × W)`, `top = floor(y × H)`, `right = ceil((x + width) × W)`, `bottom = ceil((y + height) × H)`, clamped to canvas, then `bbox = [left, top, right − left, bottom − top]`.

Save reviewer observations in `review.json`:

```json
{
  "reviewer": "human visual review at native pixels",
  "results": [
    {"id": "C1", "status": "fail", "evidence": "Handle gap", "suggested_fix": "Extend handle to rim"},
    {"id": "K1", "status": "pass", "evidence": "Fingers match source"}
  ]
}
```

- **Status**: `pass`, `fail`, or `uncertain`. Evidence must state what was seen. Optional `suggested_fix` is copied into `repair-prompt.txt`.
- **Tiny changes**: A passed `change` with < 0.5% changed pixels by 8+ levels (min 4 pixels; 16-bit grayscale 8 × 257 = 2056; float 8/255 of range) is held as invisible unless `"visible_change_confirmed": true` is set with evidence.
- **Overlapping keep boxes**: If a passed `keep` target changes pixels (e.g. contact shadow), `decision.json` lists `changed_keep_pixels`. Add `"acknowledged_changed_pixels": <count>` to that result. Candidates changing more pixels are held.

## Who writes the review

The audit accepts reviews from:
1. **Person**: `review.json` with `results`.
2. **Fresh session**: follows [independent-review.md](independent-review.md); writes `criteria` format `{"criteria": [{"id", "status", "evidence", "suggested_fix"}], "summary": "..."}`.
3. **Claude Code `image-reviewer` agent**: writes `criteria` format.
4. **Codex vision model**: convert with `python3 <skills>/image-verify/scripts/contract_to_brief.py contract.json --out brief.json`, then run `python3 <skills>/image-loop/scripts/review.py --brief brief.json --source source.png --candidate candidate.png --out vision-0 --model <vision model>` ([reviewer setup](../../image-loop/references/reviewer.md)); pass `vision-0/report.json` as `--review`.

Vision passes never override pixel checks: changed pixels outside the mask always yield `reject_technical`.

## Run and interpret

```bash
python3 <skills>/image-verify/scripts/audit_candidate.py \
  --contract contract.json --source source.png --candidate candidate.png \
  --mask final-acceptance-mask.png --review review.json --out round-0
```

- **Flags**: `--contract`, `--source`, `--candidate`, `--mask` (omit if no pixel lock), `--review`, `--out`, `--previous round-0` (checks same contract/source hashes, decided `repair`, counts repairs), `--repairs-used` (optional cross-check). Exit codes: 0 on normal run, 2 on bad arguments, unreadable files, or an invalid review (nothing written).
- **Outputs**:
  - `evidence.json`: file hashes, decoded dimensions, `pixels` (`changed_pixels`, `changed_by_target`, `visible_by_target`, `changed_outside_mask`), `repairs_used`.
  - `review.json`: the validated review, read by the next round's `--previous`.
  - `decision.json`: action from [decisions.md](decisions.md) (`accepted_by_checks`, `repair`, `hold_for_inspection`, `stop_budget`, `stop_repeated_failure`, `reject_technical`), `ids`, `protected_failed`, and `changed_keep_pixels` when a passed keep target changed. `accepted_by_checks` means the specified checks passed; it is not user approval. A `repair` decision needs another complete review; repair from the last accepted clean source or candidate, never an annotated copy or a chain of rejected outputs.
  - `repair-prompt.txt`: written for `repair`, naming failed and protected targets by source-pixel box.
- **Pixel rules**: Decoded pixels after EXIF orientation (not raw bytes). 8-bit images compared as RGBA; 16-bit and float grayscale at full precision. Bit-depth change fails. Pillow decodes 16-bit color PNGs as 8-bit, so audit refuses them with `reject_technical` (audit 8-bit or 16-bit grayscale copies). Fully transparent pixels in both images count as unchanged even if hidden RGB values differ. Grayscale with tRNS transparency counts as changed if transparent in only one image. The audit does not certify color-profile appearance or hidden layers, and script output alone cannot establish anatomy, object identity, perspective, text accuracy, or artistic quality: a person or image-capable tool must inspect the images before writing the review.

The bounded review idea was informed by [image-loop](../../image-loop/SKILL.md) and stable IDs by [image-edit-map](../../image-edit-map/SKILL.md). This helper and contract come from the earlier `image-processing-skill` project (`hbui290/image-processing-skill`, listed in the repository's NOTICE); Image Studio connects it to the image-loop reviewer through `contract_to_brief.py` and the shared `criteria` review format.
