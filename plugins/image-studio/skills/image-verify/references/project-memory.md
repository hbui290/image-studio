# Project memory and the evidence gate

`studio_state.py` keeps what a project has already settled (approved masters, deliverable specs, every defect the user reported, decisions) in a `.image-studio/` folder, and refuses to call a deliverable done until each recorded defect has a fresh crop and a verdict. It is the source of truth on every host; the plugin hooks only call it.

## Running it

```bash
python3 <skills>/image-verify/scripts/studio_state.py <command> ...
```

`<skills>` is the folder that holds the Image Studio skill folders. `approve master`, `defect add`, and `gate` read images and need Python 3.9+ with Pillow; the other commands and the hooks need only Python 3.9+. Run those three as `uv run --with pillow python3 <skills>/image-verify/scripts/studio_state.py ...` ([uv](https://docs.astral.sh/uv/)), or install Pillow once with `python3 -m pip install pillow` and use `python3` directly.

`approve`, `defect`, `brief`, `gate`, and `verdict` take `--project DIR` and find the store by walking up from it (default: the current folder); the hooks start from the `cwd` in the hook input to the first `.image-studio/` that holds a `state.json`. If `cwd` has no store, hooks check `$CLAUDE_PROJECT_DIR`, then the pointer file written at session-start (`${IMAGE_STUDIO_HOME:-~/.image-studio}/sessions/<session_id>.json`, holding the store path and pruned after 7 days; session IDs match `[A-Za-z0-9._-]{1,128}` excluding `.` and `..`, pointing to a `.image-studio` folder with `state.json`). The store is never created or found in the home folder, and `init` refuses to create a store inside a folder whose ancestor already has one.

**Exit codes:** 0 success (for `gate`: passed); 1 `gate` ran and did not pass; 2 bad input or usage, including "no store found". Hook modes always exit 0.

## Store layout

| Path | Contents |
| --- | --- |
| `.image-studio/state.json` | `schema_version`, `plugin_version_last_seen`, `brand`, `deliverables` (name → `spec` {`width`, `height`, `alpha`: `required`, `forbidden`, or `any`, `format`}, `current_sha256`, `path`), `masters` (name → `path`, `sha256`, `role`: `shape`, `color`, `logo`, or `layout`, `note`, `approved_quote`, and `replaced` history when replaced with `--quote`), append-only `decisions` ({`time`, `text`, `quote`}), and `gates` (the last passing gate per deliverable: `deliverable`, `sha256`, `run_id`, `time`, and optional `self_verified: true`) |
| `.image-studio/defects.jsonl` | One defect per line: `id` (stable: `D1`, `D2`, ...; IDs are never deleted), `deliverable`, `bbox` `[x0, y0, x1, y1]` in deliverable pixels, `kind` (`logo`, `seam`, `artifact`, `scope`, `color`, `other`), optional `master`, `master_sha256`, and ZIP `member`, `source` (`user` or `agent`), `status` (`open`, `resolved`, `wontfix`), `note`, `reported_sha256`, `region_hash`, `reported_crop`, optional `quote`, and `history` |
| `.image-studio/masters/` | Copies of approved master files, hashed |
| `.image-studio/defects/` | `D<n>-reported.png` per defect: crop of the defect region saved when reported |
| `.image-studio/gate/<run-id>/` | One folder per gate run: `D<n>-100.png` and `D<n>-200.png` per defect, `checklist.json` (run id, file hash, each defect's crop box and crop hashes), and `verdicts.json` |
| `.image-studio/stop-hook.json` | The Stop hook's marker (key hashed from session ID, turn ID, message, and store fingerprint), so the same message is not blocked twice in the same turn and store state |

## Commands

| Command | What it does |
| --- | --- |
| `init --project PATH --brand ID` | Create `PATH/.image-studio/` and print its path; refuses in the home folder or inside a folder whose ancestor has a store |
| `approve master --name N --file F --role shape\|color\|logo\|layout [--note T] [--quote T]` | Copy F into `masters/`, hash it, and record its role, a note, and the user's approving words; replacing an existing master with a different file requires `--quote` with the user's words |
| `approve deliverable --name N --file F [--width W --height H --format PNG\|JPEG\|WEBP\|ZIP] [--alpha required\|forbidden\|any] [--quote T]` | Record the spec (required the first time) and the current file hash; run it again after every accepted edit. Changing an existing spec requires `--quote` with the user's words |
| `defect add --deliverable N --bbox x0,y0,x1,y1 --kind logo\|seam\|artifact\|scope\|color\|other --note T [--master N] [--member ZIP_ENTRY] [--source user\|agent] [--quote T]` | Record a defect on the approved current file (approve the deliverable first) and print its stable ID (`D1`, `D2`, ...); saves the reported crop `defects/D<n>-reported.png` and pins `master_sha256` for logo defects; a box under 16×16 px or 0.1% of the image requires `--quote` with the user's words |
| `defect close --id D<n> --status resolved\|wontfix --note T [--quote T]` | Close a defect; its history keeps every change. `wontfix` requires `--quote` with the user's own words accepting it |
| `brief [--max-lines 40]` | Print a bounded snapshot: brand, plugin version (warns when it differs from the last one seen), defect ID gap warnings, deliverables with hashes and gate status (shows `gate passed (self-verified)` if any verdict had reviewer self), masters with roles, every open defect (never truncated), recent resolved ones, and preferences |
| `gate --deliverable N [--file F] [--run RUN] [--iou-threshold 0.90]` | Without `--run`: start a new run. With `--run`: re-check that run with its `verdicts.json`. `--file` defaults to the approved path; `--iou-threshold` can only raise the floor (0.90 to 1) |
| `verdict --run RUN --id D<n> --status pass\|fail\|uncertain --evidence T [--reviewer self\|independent] [--crop 100\|200]` | Write one verdict into the run's `verdicts.json`, with the hash of that run's crop (`--crop` defaults to 100, `--reviewer` to `self`); evidence must say what was seen, at least 10 characters |
| `pref add [--brand B] --rule T --check T [--evidence T] [--confirmed]` | Add a preference; without `--confirmed` it is a proposal for the user to confirm |
| `hook session-start`, `hook stop` | Used by the plugin hooks; see below |

## The gate

Run it in this order:

1. If the file changed since it was approved and it is the one the user should receive: `approve deliverable --name N --file F`.
2. For each defect you fixed and checked: `defect close --id D<n> --status resolved --note "what changed"`.
3. `gate --deliverable N` starts a new run, writes the crops and `checklist.json`, and prints the run ID, the report, and `Next:` with the exact commands still needed.
4. Open each crop, at 100% and 200%, and record what you saw: `verdict --run <run-id> --id D<n> --status pass|fail|uncertain --evidence "..."`.
5. `gate --deliverable N --run <run-id>` re-checks the same run with its verdicts.

`gate` exits 0 only when all of these hold:

- The file's hash equals the deliverable's `current_sha256`; otherwise it fails with "not the approved current file — run approve deliverable".
- The run was made for this file. If the file changed after the run, the run is stale and refused; start a new run, since its verdicts no longer apply.
- Dimensions, format, and alpha match the spec. For a ZIP, every image inside is checked, unopenable members with image extensions or no extension fail, duplicate member names fail, and the ZIP must not contain project memory at any depth or in nested ZIPs (`.image-studio/` or `state.json` next to `defects.jsonl` in the same folder).
- Every defect ever recorded on that deliverable, open and resolved alike, has crops in this run: its box plus a 16 px margin, clamped to the image. Resolved defects form the regression sheet; a defect added after the run needs a new run. No defect IDs may be missing (gaps between D1 and the highest ID fail), and no defect from an earlier run may have disappeared from `defects.jsonl`.
- A `resolved` defect fails when the deliverable file is unchanged since it was reported, its bbox pixels are unchanged, or fewer than 5% (≥5%) of bbox pixels changed by more than 8 per channel vs `.image-studio/defects/D<n>-reported.png`.
- For `logo` defects that name a master, the master is checked against the approved file. Logo defects pin `master_sha256`; replacing a master requires `--quote`, reported under Checked as `<id> master replaced by user: <quote>`. Hard checks fail on any background: each master component present (at least 60% stroke match), component colour, and aspect ratio within 10%. Colour-sensitive checks (IoU at least `--iou-threshold`, default 0.90 which can only be raised; extra logo strokes; flat patch; leftover background colours) fail on a plain background, but on a busy background (one that shares logo colours or varies) become inconclusive and require a `pass` verdict with `--reviewer independent`. A `logo` defect without `--master` skips this check; its verdict governs.
- Every resolved defect has a `pass` verdict in this run whose crop hash matches this run's crop, with evidence and a reviewer. A verdict from another run or with a wrong hash is rejected. `fail` counts as still failing, and `uncertain` or a missing verdict as not checked. A `wontfix` defect needs no verdict but must carry the user's quote; the report shows "accepted by user (wontfix): <quote>".
- No defect is still open.

When every check passes, `gate` prints `Result: PASS` (or `Result: PASS (self-verified — not independently reviewed)` when any verdict has reviewer `self`), records `self_verified: true` in `state.gates[NAME]`, and exits 0. `brief` then reports `gate passed (self-verified)`. The Stop hook treats self-verified and independently reviewed passes identically. Otherwise it exits 1. The report has **Checked / Not checked / Still failing** lines; pass them to the user as they are. When the gate has not passed, end the turn with the Checked / Not checked / Still failing report or a question. A verdict is a claim about pixels you saw, so write it only after opening the crop.

## Preferences

Preferences live outside projects: `${IMAGE_STUDIO_HOME:-~/.image-studio}/brands/<brand>/preferences.md` for one brand (`pref add --brand B`) and `${IMAGE_STUDIO_HOME:-~/.image-studio}/preferences.md` for all work (no `--brand`). Each entry is one line, `- [confirmed|proposed] rule — check: ... — evidence: ...`. `brief` shows the confirmed entries of the store's brand and the general file, and counts proposed ones so you can ask the user to confirm them. A file is capped at 1,500 characters; `pref add` exits 2 when it would go over, so merge entries first.

When sources conflict, the order is: the user's latest instruction, then project decisions, then brand preferences, then general preferences.

## Hooks

The plugin's `hooks/hooks.json` runs `studio_state.py hook session-start` when a session starts, resumes, or is cleared or compacted, and `hook stop` when the agent finishes a turn. Both do nothing outside a project with a store (discovering the store via `cwd`, `$CLAUDE_PROJECT_DIR`, or session pointer), and both exit 0 if `python3`, the script, or the store is missing.

- **Session start** prints the `brief`, so the agent starts with the open defects and masters in view. When it finds a store, it writes the store path into a session pointer file `${IMAGE_STUDIO_HOME:-~/.image-studio}/sessions/<session_id>.json` (pruning pointer files older than 7 days; session IDs must match `[A-Za-z0-9._-]{1,128}` excluding `.` and `..`, and pointer files must contain a string store path to a `.image-studio` folder containing `state.json`). If the store is corrupt, it prints a one-line warning (`image-studio: project store is corrupt: ...`).
- **Stop**: With a store and no valid passing gate for every deliverable (or no approved deliverable), ANY final message is blocked unless:
  - It contains an honest status report: each heading Checked / Not checked / Still failing (or Đã kiểm / Chưa kiểm / Còn lỗi) has non-empty content after it on the same line or following lines before the next heading, and the Still failing section names every open defect ID and every deliverable that has no valid gate.
  - Or it is a question: the last non-empty line ends with `?` or `？`, and no line contains a completion word (`done`, `complete(d)`, `finished`, `fixed`, `verified`, `ready`, `all set`, `all good`, `looks good`, `looks great`, `final`, `shipped`, `delivered`, `exported`, `hoàn thành`, `hoàn tất`, `xong`, `đã sửa`, `✅`, matched as whole words, case-insensitively, after NFC normalization). Messages such as "Done. Anything else?", "All good, shipped. Anything else?", or "Hoàn thành! Bạn muốn gì tiếp?" are blocked; questions like "Should I fix D1 now?" or "Bạn Đạt ơi, fix D1 không?" are allowed.
  - If no deliverable is approved yet, it blocks asking to approve deliverable first.
  - The marker in `stop-hook.json` hashes the session ID, turn ID, normalized message, and store fingerprint (defects, deliverable hashes, and gate records), so the exact same message is not blocked twice in the same turn and store state.
  - It never blocks when `stop_hook_active` is true.
  - A read-only store still blocks.
  - A corrupt store: SessionStart prints one warning; Stop blocks with the reason.

Claude Code and Codex both load plugin hooks; Codex asks the user to trust each hook first. Without hooks (an untrusted hook, a skills-only install, another host), run `brief` and `gate` yourself as the skill steps say.

## Privacy

- The store is local files only; nothing is uploaded.
- Do not record emails, account names, passwords, or other personal data in decisions, notes, or preferences.
- Never ship `.image-studio/` or project memory inside a deliverable or ZIP; `gate` fails a ZIP that contains a `.image-studio/` path at any depth (including nested ZIPs) or `state.json` next to `defects.jsonl` in the same folder.
