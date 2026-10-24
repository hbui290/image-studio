# Project memory and the evidence gate

`studio_state.py` keeps what a project has settled (approved deliverables, every reported defect, decisions) in a `.image-studio/` folder, and refuses to call a deliverable done until each recorded defect has a fresh crop and a verdict.

Run it as `python3 <skills>/image-verify/scripts/studio_state.py <command>` (`<skills>` is the folder that holds the skill folders). `defect add` and `gate` read images and need Pillow: if `python3 -c "import PIL"` fails, use `uv run --with pillow python3 ...`. Run the script; do not read its source. `--help` lists every command with an example. Exit codes: 0 ok (gate passed), 1 gate did not pass, 2 bad input or no store.

## Using the store in a skill

1. **Load once per chat.** If the session-start card is already in context, do not run `brief`; a skill handing off to another does not reload. Otherwise run `brief`.
2. **Create a store only when needed:** the user reports a defect, approves a deliverable, or asks for one. `init --project <folder> --brand <brand>` (never the home folder or inside a folder that already has a store). The first `approve deliverable --name N --file F` needs `--width W --height H --format PNG` (and `--alpha required|forbidden|any`).
3. **Record what the user reports:** `defect add --deliverable N --bbox x0,y0,x1,y1 --kind seam|artifact|scope|color|logo|other --note "..."`. Use `--kind scope --quote "the user's words"` for a change the user asks for that is not a mistake (new text or date, removing an element they no longer want): it needs no lesson, and the gate only checks that its box visibly changed (0.5% of pixels instead of 5%). Without the user's words it is treated like any other defect; never use it for your own mistake. A defect that covers most of the image (for example "the whole poster looks soft") is not a local repair: ask the user whether to regenerate the whole image, run image-enhance, or accept it (`defect close --status wontfix --quote "<their words>"`).
   Problems the agent finds itself (the [designer review](designer-review.md) hunt) are added with `--source agent`; `map --deliverable N --out defect-map.png` draws every open defect on one image so the user confirms them all at once.
4. **Learn from a miss after delivery.** When the deliverable had already passed the gate, `defect add` says so and marks the defect: also run `lesson add --defect D<n> --mistake "..." --cause "..." --check "..."` (what went wrong, why, and what to check next time). The gate does not pass until that lesson exists. If you delivered without a passing gate and the user rejects the result, add a lesson anyway (without `--defect` when nothing was recorded). Lessons are shared by every task (`${IMAGE_STUDIO_HOME:-~/.image-studio}/lessons.jsonl`); the session-start card and `brief` show the 5 most relevant. When `lesson add` reports that the same kind of mistake happened in 2 or more tasks, ask the user whether to make it a rule (`pref add`, with `--confirmed` only after they agree).
5. **Gate once per delivery attempt**, before telling the user it is done; not after every repair round (a repair round checks its region with `edit-check --before A --after B --bbox x0,y0,x1,y1`, which needs no store). Re-run only after a further fix. Deliver only after it exits 0.
6. **Talk to the user in plain words.** Defect IDs are internal; mention them only in parentheses. When the gate has not passed, say what is still wrong and ask what to do.

## Taste and lessons

The goal is a designer that gets closer to the user's taste with every task. Both files are shared by every task, under `${IMAGE_STUDIO_HOME:-~/.image-studio}`, and are recorded with or without a project store. Inside a store the session-start card and `brief` show them; outside one, read them with `taste list [--brand B]` and `lesson list`.

- **Taste:** when the user approves or praises a result ("love this", "keep this one", or the same in the user's language, e.g. Vietnamese "đẹp", "giữ cái này"), record what they liked: `taste add --aspect color|line|composition|detail|lighting|text|style|other --note "what they liked, concretely" --quote "their words"` (add `--deliverable N` in a project). Notes go to `brands/<brand>/taste.jsonl` (the store's brand, or `--brand`), else `taste.jsonl`. The session-start card and `brief` show the 6 newest notes, brand and general merged, under "Your taste"; match them in the first draft.
- **Lessons:** besides a miss after delivery (step 4 above), record a method that failed twice and the one that then worked: `lesson add --mistake "..." --cause "..." --check "..." --worked "..."`.
- **Repeats and construction rules:** `defect add` records the image size each defect was reported on (`image_size`). A `--source user` defect whose box covers the region of an earlier user complaint is a repeat: any status, on an image of the same size or of the same artwork rescaled or slightly cropped (width/height within 2%, boxes compared as fractions of the image), with an IoU of at least 0.1, its center inside the earlier box, or at least 60% of the earlier box inside it. `defect add` prints "Repeat: this region was already reported (D<n>)" and records `repeat_of`, `needs_construction`, and `needs_lesson`. Agent defects and `scope` requests with the user's words are never repeats and never count as earlier complaints. Stop patching strokes and follow [construction-reference.md](construction-reference.md), then record how the object is built: `construction add --defect D<n> --object "..." --rule "..." (--ref FILE [--ref FILE ...] | --quote "the user's words")`. Each `--ref` must be a readable image; its path (relative to the project when inside it) and sha256 are stored in the store's `construction.jsonl`. `construction list` prints every rule; the session-start card and `brief` show the 3 newest. Also run `lesson add --defect D<n>`.
- Neither changes a rule or a skill by itself. A repeated pattern becomes a rule only through `pref add --confirmed` after the user agrees.

## Brand kit

Hard facts for a brand, set with the user: `brand set --brand B --color NAME=#RRGGBB[:role] --font ROLE=Family --logo FILE --ref FILE=role --do "..." --dont "..."` (repeat flags as needed; `--remove colors:NAME|fonts:ROLE|refs:FILE|do:TEXT|dont:TEXT|logo`). It lives in `${IMAGE_STUDIO_HOME:-~/.image-studio}/brands/<brand>/brand.json` (4,000 characters at most) and records the hash of the logo and each reference. `brand show` prints it and flags a logo or reference that is missing or changed; the session-start card shows a one-line summary.

- Use the palette, fonts, and do/don't lists in the [style block](../../image-create/references/prompt-blocks.md).
- The logo is composited from that exact file, never redrawn.
- Approved references, and files the user sends in the chat, are the only existing images that may be used as style references or pixels. Never search the disk for others. Real photos found to understand how an object is built ([construction-reference.md](construction-reference.md)) are never used as pixels or style.
- Add an entry only when the user states or approves it; taste notes are for impressions, the brand kit for exact values.

## The gate

```bash
python3 <skills>/image-verify/scripts/studio_state.py approve deliverable --name N --file F   # only if the file changed
python3 <skills>/image-verify/scripts/studio_state.py defect close --id D<n> --status resolved --note "what changed"
python3 <skills>/image-verify/scripts/studio_state.py gate --deliverable N            # prints Run: <id> and Next: steps
python3 <skills>/image-verify/scripts/studio_state.py verdict --run <id> --id D<n> --status pass --evidence "what the crop shows" [--reviewer independent]
python3 <skills>/image-verify/scripts/studio_state.py verdict --run <id> --from verdicts.json   # or every verdict at once: [{"id": "D1", "status": "pass", "evidence": "..."}]
python3 <skills>/image-verify/scripts/studio_state.py gate --deliverable N --run <id>
```

Open the 100% crop of each defect first; open the 200% crop only when the 100% view is unclear. Write verdicts one call at a time (one `--from` file holds them all; parallel calls overwrite each other), and only after opening the crop; use `fail` or `uncertain` when it is not clearly fixed.

`gate` passes only when: the file's hash equals the approved one and matches the spec; every defect ever recorded on the deliverable (open and resolved, so fixed defects are re-checked) has crops in this run and no IDs are missing; no defect is open; each resolved defect has a `pass` verdict tied to this run's crop and at least 5% of its box changed since it was reported (0.5% for `scope` requests that carry the user's words); each `wontfix` carries the user's words; each defect reported after delivery (other than a `scope` request with the user's words) has a lesson; each repeat defect has a lesson and a construction rule (`construction add --defect D<n>`). A resolved defect whose pixels are identical to an earlier passing run keeps that verdict automatically ("unchanged since run ..."), so each gate only needs verdicts for regions that changed. A ZIP deliverable's spec is checked by hash and size only; a defect needs a single-image ZIP and is cropped from that image. Self-verified passes are labelled as such.

## Preferences

`pref add [--brand B] --rule T --check T [--confirmed]` stores one-line rules in `~/.image-studio/` (per brand or general, 1,500 characters each). Without `--confirmed` it is a proposal for the user to confirm. Precedence: the user's latest instruction, then project decisions, then brand, then general preferences.

## Hooks

- **Session start** (and after compaction) prints a short card: open defects, deliverables and gate status, the 3 newest construction rules, recent decisions, the user's taste (6 newest notes), up to 5 lessons from earlier tasks, confirmed preferences.
  When the chat's transcript is over 25 MB, the card adds a line suggesting a new chat for a new task, since every step resends the whole history.
- **Stop** blocks only a completion claim ("done", "fixed", "ready", or Vietnamese "xong", "hoàn thành"...) while a deliverable has not passed the gate or a defect is open, once per message. The agent then tells the user plainly what is still wrong. Questions, progress updates, and negated claims ("not done", Vietnamese "chưa xong") pass; a claim followed by a question ("Done. Anything else?") still counts. A Checked / Not checked / Still failing report passes only when it names something not checked or still failing. A session working in a separate git repo below the project folder is not policed.
- Both hooks exit 0 silently when python3, the script, or a store is missing. Codex asks the user to trust each hook once; without hooks, run `brief` and `gate` as the steps say.

Keep the store local; never ship `.image-studio/` inside a deliverable, and do not record personal data in notes.
