# Project memory and the evidence gate

`studio_state.py` keeps what a project has settled (approved deliverables, every reported defect, decisions) in a `.image-studio/` folder, and refuses to call a deliverable done until each recorded defect has a fresh crop and a verdict.

Run it as `python3 <skills>/image-verify/scripts/studio_state.py <command>` (`<skills>` is the folder that holds the skill folders). `defect add` and `gate` read images and need Pillow: if `python3 -c "import PIL"` fails, use `uv run --with pillow python3 ...`. Run the script; do not read its source. `--help` lists every command with an example. Exit codes: 0 ok (gate passed), 1 gate did not pass, 2 bad input or no store.

## Using the store in a skill

1. **Load once per chat.** If the session-start card is already in context, do not run `brief`; a skill handing off to another does not reload. Otherwise run `brief`.
2. **Create a store only when needed:** the user reports a defect, approves a deliverable, or asks for one. `init --project <folder> --brand <brand>` (never the home folder or inside a folder that already has a store). The first `approve deliverable --name N --file F` needs `--width W --height H --format PNG` (and `--alpha required|forbidden|any`).
3. **Record what the user reports:** `defect add --deliverable N --bbox x0,y0,x1,y1 --kind seam|artifact|scope|color|logo|other --note "..."`. A defect that covers most of the image (for example "the whole poster looks soft") is not a local repair: ask the user whether to regenerate the whole image, run image-enhance, or accept it (`defect close --status wontfix --quote "<their words>"`).
4. **Gate once per delivery attempt**, before telling the user it is done; not after every repair round. Re-run only after a further fix. Deliver only after it exits 0.
5. **Talk to the user in plain words.** Defect IDs are internal; mention them only in parentheses. When the gate has not passed, say what is still wrong and ask what to do.

## The gate

```bash
python3 <skills>/image-verify/scripts/studio_state.py approve deliverable --name N --file F   # only if the file changed
python3 <skills>/image-verify/scripts/studio_state.py defect close --id D<n> --status resolved --note "what changed"
python3 <skills>/image-verify/scripts/studio_state.py gate --deliverable N            # prints Run: <id> and Next: steps
python3 <skills>/image-verify/scripts/studio_state.py verdict --run <id> --id D<n> --status pass --evidence "what the crop shows"
python3 <skills>/image-verify/scripts/studio_state.py gate --deliverable N --run <id>
```

Open the 100% crop of each defect first; open the 200% crop only when the 100% view is unclear. Write verdicts one at a time (parallel writes overwrite each other), and only after opening the crop; use `fail` or `uncertain` when it is not clearly fixed.

`gate` passes only when: the file's hash equals the approved one and matches the spec; every defect ever recorded on the deliverable (open and resolved, so fixed defects are re-checked) has crops in this run and no IDs are missing; no defect is open; each resolved defect has a `pass` verdict tied to this run's crop and at least 5% of its box changed since it was reported; each `wontfix` carries the user's words. A ZIP deliverable's spec is checked by hash and size only; a defect needs a single-image ZIP and is cropped from that image. Self-verified passes are labelled as such.

## Preferences

`pref add [--brand B] --rule T --check T [--confirmed]` stores one-line rules in `~/.image-studio/` (per brand or general, 1,500 characters each). Without `--confirmed` it is a proposal for the user to confirm. Precedence: the user's latest instruction, then project decisions, then brand, then general preferences.

## Hooks

- **Session start** (and after compaction) prints a short card: open defects, deliverables and gate status, recent decisions, confirmed preferences.
- **Stop** blocks only a completion claim ("done", "fixed", "xong", "hoàn thành"...) while a deliverable has not passed the gate or a defect is open, once per message. The agent then tells the user plainly what is still wrong. Questions, progress updates, negated claims ("chưa xong"), and reports with Checked / Not checked / Still failing headings pass. A session working in a separate git repo below the project folder is not policed.
- Both hooks exit 0 silently when python3, the script, or a store is missing. Codex asks the user to trust each hook once; without hooks, run `brief` and `gate` as the steps say.

Keep the store local; never ship `.image-studio/` inside a deliverable, and do not record personal data in notes.
