# Changelog

## 2.2.3 (2026-10-02)

Cutout edge cleanup for transparent PNGs, plus fixes from a third review. Every behavior fix has a regression test (164 tests before, 172 after).

- **image-enhance, new:** `compare_display.py` now handles transparent images. It shows them on a dark backdrop (`before-after.png`) and a light one (`before-after-light.png`), measures edge noise at display size against the source (`edge_ratio`: at most 0.8 counts as a visible improvement, above 1.1 fails), and fails a changed cutout shape (`alpha_iou` below 0.97). A new "Cutout edges" recipe removes a halo or speckled rim by shrinking and softening the alpha edge one display pixel at a time. image-inspect routes jagged or outlined cutout edges to it.
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
