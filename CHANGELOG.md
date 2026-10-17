# Changelog

## 2.4.0-local.1 (2026-10-18)

Lighter and faster, closer to the owner's image-processing plugin. Measured on a real 414-minute Codex poster job: each repair pass loaded 18-26k tokens of docs and re-read them after every compaction, the gate ran about 20 times, and the Stop hook made the agent list defect IDs in every message.

- **image-create, image-inspect, image-repair, image-verify:** each SKILL.md is a short checklist of about 2.5 KB. Detail moved to references that are read only when a stated condition holds. Each says to run scripts and use `--help` instead of reading their source.
- **image-repair:** `brand-repair-gates.md` and `repair-history.md` are merged into `references/repair-rules.md`, scoped to exact logos, packaging text, transparent exports, and multi-chat repair notes. `repair-and-composite.md` and `tool-readiness.md` are shorter, with a quick preflight.
- **studio_state.py:** about half the size. Removed features that were never used: logo matching, `approve master`, `defect add --master/--member`, the ZIP member scan (a ZIP deliverable is checked by hash and size), `gate --iou-threshold`, and the plugin-version warning. Old stores stay readable. `--help` is a full cheat sheet.
- **hooks:** the Stop hook blocks only a completion claim while the gate has not passed or a defect is open, and asks the agent to tell the user plainly what is still wrong; progress updates, questions, and negated claims pass. A session working in a separate git repo below the project folder is not policed. SessionStart prints a card of at most 2,400 characters. Timeouts are 10 s and 5 s.
- **project-memory.md:** rewritten to about 4.5 KB: create a store only when needed, load it once per chat, gate once per delivery attempt, 100% crops first, and defect IDs stay internal.

## 2.3.1-local.1 (2026-10-17)

Regenerate patch material by default and streamline project-memory workflow, measured from a real session where the agent searched for and pasted existing art instead of regenerating, and duplicated gate instructions created heavy per-round overhead.

- **image-repair:** regenerate patches by default via host image generators (`image_gen.imagegen` in Codex; host tools in Claude Code) rather than searching disk for replacement artwork or reusing existing images; composite existing pixels only from user-supplied files or for exact logos and packaging text. Object removal residue checklist now reuses gate defect crops rather than requiring separate extra crops.
- **brand-repair-gates:** narrow gates to exact logos, packaging text, and transparent exports; masters limited to logos and brand marks. If detail degrades, restart from the approved image and regenerate with tighter crops, masks, or references instead of searching for or pasting other artwork. Stop conditions now link directly to `stop_repeated_failure`.
- **project-memory:** consolidate store and gate instructions into a single canonical "Using the store in a skill" reference in `image-verify/references/project-memory.md` rather than repeating them across 5 skills. Load memory once per session; create stores only when defects, brand marks, or user requests warrant one; run the gate once before delivery rather than every repair round; open 200% crops only when 100% is unclear; run verdicts one at a time; guide whole-image defects toward regeneration, enhancement, or wontfix.
- **image-inspect, image-create:** clarify source-art pointers to refer to user-supplied files.

## 2.3.0-local.1 (2026-10-17)

Project memory and an evidence gate, so an agent remembers approved work and open defects across chats and cannot claim "done" without checked evidence. Built from a review of a real session where most corrections came from false completion claims and forgotten approved designs.

- **image-verify:** new `scripts/studio_state.py` keeps a project store in `.image-studio/` (deliverables with approved hashes, masters with roles and replacement history, append-only decisions, stable defect IDs in `defects.jsonl`, and reported crops in `defects/`) and bounded per-brand and general preferences in `~/.image-studio/`. `init` refuses inside the home folder or inside a folder whose ancestor has a store. Replacing an approved master on an existing name with a different hash requires `--quote`; logo defects pin `master_sha256` and report a quoted replacement as "master replaced by user". `defect add` saves reported region crops and rejects a bbox under 16×16 px or 0.1% of the image unless `--quote` records the user's words. `brief` prints a bounded snapshot that never drops an open defect, and warns on defect ID gaps or when the plugin version changed. `gate` checks the approved file hash, size, format, and alpha, failing on defect ID gaps or disappeared defects. For ZIP deliverables, every image is checked, unopenable extensionless or image members fail, and project memory (`.image-studio/` at any depth or nested ZIP, or `state.json` next to `defects.jsonl` in the same folder) fails. The gate writes 100% and 200% crops of every defect, and passes only when every defect has a verdict tied to this run's crops and none is open. A defect marked resolved fails while its pixels are unchanged or fewer than 5% of bbox pixels changed by >8 per channel vs `.image-studio/defects/D<n>-reported.png`; `wontfix` and a changed deliverable spec need the user's words (`--quote`); the IoU threshold can only be raised. On a busy background colour-sensitive logo sub-checks become inconclusive (requiring `--reviewer independent`), while hard fails stay for missing components, component colour, and aspect ratio. The gate re-renders a reused run's crops and refuses edited checklists and forged gate records. Reference: `references/project-memory.md`.
- **hooks:** the plugin ships `hooks/hooks.json`. At session start it prints the brief of the project store, printing one warning if the store is corrupt. At stop, with a store and no valid gate (or no approved deliverable), ANY final message is blocked unless it contains all three report headings Checked / Not checked / Still failing (or Đã kiểm / Chưa kiểm / Còn lỗi; heading followed by ":" or line end) or is a question (last non-empty line ends with ? or ？); keyword claim detection is removed. The marker combines session, turn, message, and store fingerprint, never blocking when `stop_hook_active` is true. A read-only store still blocks, and a corrupt store blocks with the reason. Both hooks exit 0 silently when python3, the script, or a store is missing. Codex asks you to trust each hook once.
- **image-repair, image-verify, image-loop, image-edit-map, image-enhance:** step 0 loads project memory and records user-reported defects; the last step before delivery runs the gate and reports Checked / Not checked / Still failing.
- **image-repair:** repair history reuses the store's defect IDs; `defects.jsonl` is the source of truth for status.
- **image-repair, image-loop, image-verify:** add a task-level repair history for carrying source coordinates, rejected methods, and review evidence across rounds and chats. Repeated defects require a different method. This explicit handoff record complements project memory; neither feature is automatic model learning.
- **image-repair:** object removal now requires a distinct residue sweep for frame edges/corners, border fragments, glow/color spill, shadows, and occluded slivers; “no recognizable silhouette” alone cannot pass. Added after a review missed small card-colored strokes behind a dragon horn.

## 2.2.5-local.2 (2026-10-17)

Fixes from a fifth review. Every behavior fix has a regression test (180 tests before, 207 after).

- **image-loop:** `review.py` ends a damaged candidate (for example a TIFF whose later frame has no dimensions) with a clear message and exit 2 instead of a traceback, and finds the transparent pixels of a 16-bit grayscale PNG that uses a tRNS value.
- **image-verify:** in 16-bit and float images the audit counts a pixel whose transparency changed as changed, holds a change below 8 levels (8 × 257 in 16-bit, 8/255 of the value range in float) as barely visible, and treats a tRNS value that no pixel uses as opaque. The 0.5% barely-visible threshold no longer rounds down.
- **image-enhance:** `compare_display.py` accepts a faithful resize of a very wide image and rejects a crop of a very tall one (aspect checked to within 1 pixel of rounding), refuses floating-point images and a `--width` beyond Pillow's pixel limit with exit 2. The 16-bit test fixture now saves on Pillow 13.
- **image-edit-map:** `validate_spec.py --image` says dimensions were not verified when the spec does not report them, exits 2 for a missing or unknown `--image-id`, requires a reason in the note of an unknown observation, and requires section IDs to carry their image prefix.
- **image-reconstruction:** `validate` refuses unpaired surrogate code points, `compile --mode edit` requires the target attachment to have a path, and `visual-map.html` now refuses inherited property names and integers written as floats, matching the script.
- **image-repair:** brand repair gates name the `stop_repeated_failure` rule and drop a maintainer-only note.

## 2.2.5-local.1 (2026-10-17)

- Document brand repair gates: freeze approved sources, distinguish material from silhouette references, inspect old-logo removal before placement, and review every logo occurrence.
- Document mask-alpha and composite-state pitfalls, opaque-body checks for cutouts, repeated-failure stops, and final-export/ZIP visual review. Local documentation release only; no image-model or script behavior changed.

## 2.2.4 (2026-10-02)

Fixes from a fourth review. Every behavior fix has a regression test (173 tests before, 180 after).

- **image-enhance:** `compare_display.py` no longer fails a see-through body made solid as a color grade: when the body is made solid, color and fidelity are measured with the source's opacity and the edges against the source with its body made solid.
- **image-enhance:** an object whose alpha stays below 128 (a faint or ghost cutout) now has a shape: the cutout is taken where alpha is at least half the image's highest alpha, so `body_alpha` and `alpha_iou` report it instead of 255 and 0.
- **image-enhance:** when `--width` is wider than the source, edges are judged at the source width (new `edge_width` metric). The enlarged source has smooth, interpolated edges, so a clean AI upscale was failing as "noisier" (`edge_ratio` 3 to 5 at 2048 px for a 1024 px file).
- **image-enhance:** 16-bit grayscale input works on Pillow before 9.
- **image-enhance recipes:** the solid-backdrop hole fill works (`-draw 'color … floodfill'` added an alpha channel that `-negate` then inverted, so dark parts of the object stayed transparent). The edge-shrink loop works on the upscaled file from the step before. The card-pack measurements were redone and replace numbers that could not be reproduced.
- **image-verify:** a 16-bit grayscale mask with a transparent gray value (PNG tRNS) now locks those pixels, as the docs say.
- **image-reconstruction:** `reconstruct.py` rejects numbers beyond 2^53 − 1 with a clear message (a 400-digit integer was a traceback) and checks long dependency chains without recursion. `visual-map.html` now matches it on duplicate JSON keys, Python whitespace (U+001C–U+001F, U+0085, U+FEFF), `casefold` of ß and final sigma, property names that are plain numbers (both reject them), and long dependency chains.
- **Docs:** the `edge_ratio` limit states its 0.1 allowance for tiny values.
- **image-enhance:** a see-through body fails only when the candidate is more see-through than the source, so a model trial on a crop of an already see-through file is not failed for it.
- **Workflow from a Codex card-pack session:** new "Logo to vector" recipe (Potrace per color, layered SVG, render-and-compare check; Potrace added to the tools); the cutout-edge order gains "redraw a simple outline as a vector path" before regeneration, and says to verify a redrawn or regenerated edge with an image-verify contract and edge-only mask instead of `compare_display.py`, which reports any edge repair as changed content; image-repair says to measure and match alignment marks after placing a logo; image-verify says what to do in Codex, which has no `image-reviewer` agent.

## 2.2.3 (2026-10-02)

Cutout edge cleanup for transparent PNGs, plus fixes from a third review. Every behavior fix has a regression test (164 tests before, 172 after).

- **image-enhance, new:** `compare_display.py` now handles transparent images. It shows them on a dark backdrop (`before-after.png`) and a light one (`before-after-light.png`), measures edge noise relative to the noise inside the object at display size, against the source (`edge_ratio`: at most 0.8 counts as a visible improvement, above 1.35 fails), fails a changed cutout shape (`alpha_iou` below 0.97), and fails a see-through body (`body_alpha` below 254, as image generators often write). A new "Cutout edges" recipe works in order: check that the transparency is real, upscale (directly, or over a gray that touches only fully transparent pixels), shrink and soften the alpha edge one display pixel at a time, make the body solid, and, when shrinking is not enough, regenerate the edge through image-repair in two passes. New recipes keep small text from the source during an AI upscale and cut out an object on a solid backdrop with the mask built before upscaling. image-inspect and image-repair route jagged or outlined cutout edges to the recipe.
- **image-enhance:** a `--crop` at the far edge of a candidate smaller than the source no longer shows black padding (a 2.2.2 regression).
- **Installer:** `--to` may be a symlink to another disk; the staging folder now sits next to the real folder, so the final rename no longer fails with "Cross-device link".
- **image-reconstruction:** the visual map treats the Turkish dotless i (ı) like Python's `casefold`, so it no longer refuses preserve/allow terms that `reconstruct.py` accepts.

## 2.2.2 (2026-10-02)

Fixes from a bug hunt on 2.2.1. Every behavior fix has a regression test (159 tests before, 164 after).

- **image-inspiration:** a budget stop with an unproven improvement (`improved: null`) now keeps the incumbent as `winner_id` and reports the judge's favourite as `ranked_first`, like `stop_uncertain_comparison`.
- **image-reconstruction:** the visual map now refuses what `reconstruct.py` refuses: properties on `keep` or `remove`, non-bbox properties on `move`, and preserve/allow terms that match only after case folding (Straße and STRASSE). It shows the edit prompt only when a selection changes something. `reconstruct.py` reports an oversized number as an error with exit 2 instead of a traceback.
- **image-loop and image-verify:** camera JPEGs saved as MPO (a JPEG with an embedded preview) are checked as still JPEGs instead of being refused as animated. The audit refuses an animated mask instead of silently using its first frame.
- **image-enhance:** `--crop` on a candidate smaller than the source no longer fails when a small box rounds to zero pixels.
- **Repo hook:** the LICENSE/NOTICE guard also asks when the path differs only in letter case, and ignores a non-text `file_path` instead of crashing.
- **Docs:** the reverse-engineering and inspiration example notes match what the current scripts do; skill names are written as bare names; Codex CLI, ImageMagick, and uv have official links; the 2.2.0 entry has its date.

## 2.2.1 (2026-10-01)

Fixes from a full audit of 2.2.0. Every behavior fix has a regression test (137 tests before, 159 after).

- **Data safety:** `install.py --replace` restores every skill when interrupted; input errors exit 2, and an empty `--to` is refused.
- **Crashes and wrong results:**
  - `review.py`: decodes `--source` and refuses unreadable or animated sources; malformed `--previous` files and non-object reviewer output no longer crash; invalid model reports keep their reason.
  - `compare_display.py`: 16-bit grayscale sources are scaled instead of clipped; `--width` is limited to 16384; a failed crop leaves no half-written folder.
  - `visual-map.html`: its prompt compiler and embedded schema now match `reconstruct.py` (the edit prompt had dropped PRESERVE and REQUIRED RESULT).
  - `combine.py`/`advance.py` exit 2 on bad input; `validate_spec.py` checks element IDs and handles deep JSON; the audit and `review.py` refuse format `JPG` (use `JPEG`) and agree on the review format.
- **Docs:** rewritten usage guides for image-create, image-inspect, image-reverse-engineer, image-enhance and image-reconstruction; routing between sibling skills; commands, flags and exit codes checked against the code; upscaler model folders explained (a missing model gave a black image with exit 0).
- **Examples:** the tavern hero case now matches the real record and includes anonymized before/after images and crops, shown at the top of the README and linked from `image-repair` and `image-enhance`.
- **Repo:** `CLAUDE.md` rules, Claude Code hooks that guard the attribution files and check Python 3.9 syntax, CI with read-only permissions and pinned actions.

## 2.2.0 (2026-10-01)

Added image-enhance with `compare_display.py`, the visible-change gate in the audit, and audit fixes.
