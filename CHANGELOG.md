# Changelog

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

## 2.2.0

Added image-enhance with `compare_display.py`, the visible-change gate in the audit, and audit fixes.
