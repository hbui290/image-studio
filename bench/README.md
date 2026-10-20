# Defect-hunt benchmark

Measures how many real defects the `image-hunter` agent finds, so a change to the hunt rules can be judged by numbers instead of impressions. Development only: this folder is not part of the plugin.

## Cases

Each case is a folder in `bench/cases/`:

- `image.png`: a copy of a real image with known defects (never the user's original);
- `truth.json`: the answer key, labelled and confirmed by the owner, not by the agent being measured:
  ```json
  {"image": "image.png", "size": [3840, 2160],
   "defects": [{"id": "D1", "box": [812, 640, 905, 760], "kind": "hand", "note": "six fingers on the sword hand"}]}
  ```
  Use these `kind` values: `hand`, `anatomy`, `text`, `straight-prop`, `seam`, `edge`, `color`, `extra-object`, `missing-object`, `other`.

## Run

1. Make the review views: `python3 plugins/image-studio/skills/image-verify/scripts/studio_state.py prepare-review --image bench/cases/NAME/image.png --out bench/runs/NAME/views`.
2. Give the views folder and the image size to the `image-hunter` agent, with no hints about the answer key, and save its table to `bench/runs/NAME/found.md`.
3. Score it:
   ```bash
   python3 bench/score.py --truth bench/cases/NAME/truth.json --found bench/runs/NAME/found.md
   ```

A found box counts when it overlaps a labelled box by IoU 0.1 or more, or its center falls inside it; matching is one to one, and "whole image" rows or boxes covering a quarter of the image never count. Report recall per kind (what was missed matters most) and precision (boxes that point at nothing). Keep `bench/runs/` out of git; record the summary numbers in the CHANGELOG entry that changes the hunt.
