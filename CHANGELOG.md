# Changelog

## 2.22.0-local.1 (2026-10-20)

Optional numpy + OpenCV engine and three OpenCV features. Pillow and jsonschema stay the only required dependencies; every check also runs on Pillow alone with the same verdict.

- **Engine (`image-verify/scripts/accel.py`):** `axis-check`, `blend`, `edit-check`, `shape-check` and `mask-from-diff` take `--engine auto|pillow|fast` (else `IMAGE_STUDIO_ENGINE`, else auto) and print `Engine: numpy/opencv` or `Engine: pillow` first. auto uses `numpy==2.0.2` and `opencv-python-headless==4.11.0.86` when both import (pins chosen for Python 3.9); fast without them exits 2 with the install line. Vectorized: changed-pixel masks, mask growing (cv2.dilate), the blend ring, ring CIEDE2000, `seam_step`, pixel counts, and the shape-check boundary distance (exact cv2.distanceTransform). Blend output pixels are identical on both engines. `audit_candidate.py` already diffs with Pillow's C operations (no per-pixel loop) and is unchanged; the axis-check blade trace is at most 200 profiles (0.17 s on 4K) and stays as is.
- **4K timings** (3840x2160, macOS arm64, Python 3.9, best of 3; "pixel work" excludes PNG decode/encode, which both engines share):

  | Command | Pillow total | numpy/OpenCV total | Pillow pixel work | numpy/OpenCV pixel work | Speed-up (pixel work) |
  | --- | --- | --- | --- | --- | --- |
  | `blend` | 1.23 s | 0.69 s | 0.64 s | 0.09 s | 7.0x |
  | `edit-check --mask --edge 8` | 0.76 s | 0.39 s | 0.45 s | 0.08 s | 5.5x |
  | `shape-check` | 0.16 s | 0.10 s | 0.15 s | 0.09 s | 1.7x |
  | `axis-check` | 0.20 s | 0.20 s | 0.17 s | 0.17 s | 1.0x |

  A fresh process adds about 0.1 s to import numpy and OpenCV.
- **`align-check --auto` (needs OpenCV):** finds `--at` with cv2.matchTemplate (TM_CCOEFF_NORMED) over patch scales 0.90-1.10, refined at full size; with `--mask` it matches only the patch's context outside the mask. Prints `Auto: best match at X,Y, scale S, score V` and writes that position into the views and `align.json`, so `--accept` and `blend --align` use it. Exit 1 with nothing written when the score is under 0.8, another place scores within 0.01 (a repeated motif), or the patch or its masked context is flat (std under 2 levels; TM_CCOEFF_NORMED scores a flat template 1.0 everywhere) ("no reliable match ... give --at"); equal scores prefer the scale closest to 1, or when the scale is more than 1% from 1 ("the patch must be resized"; it never resizes for you).
- **`mask-from-diff --before B --after A --out M.png [--threshold 24] [--grow 5] [--min-area 16]`:** changed pixels (a channel differs by more than the threshold), components under `--min-area` px dropped (cv2.connectedComponentsWithStats, or the same 8-connected filter in pure Python by run labeling: both engines write the same mask), grown by `--grow` px; writes a 0/255 gray PNG, refuses to overwrite its inputs, exit 1 without a file when nothing changed.
- **`seam_grad` in blend (OpenCV):** mean Sobel gradient on the band across the mask edge, output against base; report only.
- **axis-check:** takes `--engine` but measures the same way on both engines (least-squares spine tilt), so verdicts cannot differ. Real swords (copies): v56 passes (spine 24 px off, 0.9 deg), v51 fails (spine 31 px off the red line; hilt left of the blade axis).
- **Tests and CI:** `tests/test_accel.py` runs each accelerated command on both engines with the same inputs and requires the same exit code and numbers within 1%; fast-only tests skip without numpy/OpenCV. CI adds Python 3.9 and 3.12 jobs with the pinned numpy and OpenCV.

## 2.21.0-local.1 (2026-10-20)

Closes the gaps left after comparing with the closest competitors. No new dependency.

- **No blend without registration (idea from Frame-Patcher):** `align-check` writes `align.json`; after looking at `checker.png` and `overlay.png`, `align-check ... --accept` marks it accepted. `blend --align D/align.json` refuses unless it is accepted and the inputs and `--at` still match; `--no-align-check` skips it with a warning.
- **`shape-check --before-mask A --after-mask B` (idea from aeolo-image-fidelity):** a protected object keeps its silhouette: IoU at least 0.99, box aspect change at most 1%, boundary moved at most max(2 px, 0.1% of the long side). About 0.3 s on 4K masks.
- **`crop-check --image I --focus BOX [--display WxH] [--out-dir D]` (from slop-cop, MIT):** checks that the subject survives 16:9, 4:5, 1:1 and 9:16 crops and that the image is at least twice the display size.
- **Exact text in `compose_layers.py` (adapted from scenario-labs/skills, MIT):** text layers take a `box` with `overflow` wrap / shrink / clip and `align`; shrink finds the largest size that fits or exits 2; PNG output embeds the resolved layout in an `image-studio-layout` text chunk.
- **Benchmark (development only):** `bench/score.py` scores an `image-hunter` table against an owner-labelled answer key (recall per defect kind, precision); see `bench/README.md`.

## 2.20.0-local.1 (2026-10-20)

Lessons from nine similar projects on GitHub (credits in NOTICE). No new dependency.

- **`edit-check --mask M [--edge PX]`:** checks a masked edit pixel by pixel: share of mask pixels changed (over 12/255), noise outside (over 8/255, reported) and real changes outside (over 12/255, fail above 0.1%). A mask that changed under 0.5% fails as "no effect or inverted". `--edge` skips the feather band `blend` adds.
- **`blend` measures the seam:** default feather is 3% of the mask box's short side (2-8 px, warning above 5%); prints CIEDE2000 between patch and base on the ring outside the mask and fails (exit 1, output still written) above mean 2.0 or p95 3.5; prints `seam_step` (mean lightness jump across the mask edge) next to the base's own value.
- **`align-check --base --patch --out-dir D [--at X,Y] [--mask M]`:** writes `checker.png` and a 50/50 `overlay.png` to see misalignment before compositing, and refuses a patch whose aspect ratio is more than 1% off. Repair docs no longer force-stretch a patch with `-resize WxH!`.
- **Gate:** a size mismatch says whether the aspect ratio is also off (over 0.025); a deliverable over 1 MB gets a warning.
- **Reviewer:** starts fresh each round with no old scores, editor prompts or "it is better now"; names one concrete visible detail per image or the review does not count; answers each earlier finding as still serious / no longer prominent / gone, on the same crops.
- **Hunter:** traces each arm from shoulder to exactly one hand, counts fingers hand by hand, transcribes text verbatim, reads product labels letter by letter ("unverified" when unreadable), judges each panel of a grid on its own, checks each reference for leaks, and flags copy that contradicts its chart.
- **Install for other agents:** `npx skills add hbui290/image-studio --skill '*'`.

## 2.19.0-local.1 (2026-10-20)

Lessons from the links and experiments in codejunkie99/image-loop: the prompt-lab experiment records, OpenAI's GPT Image 2.5 prompting and vision guides, and the papers it cites (M3 2602.06166, DSG 2310.18235, Attend-and-Excite, GenEval, T2I-CompBench).

- **One failure per repair round:** an image-loop `repair` decision names one `focus` check (protected first, then brief order) and `repair-prompt.txt` fixes only that one, leaving the other failures for later rounds. `ids` still lists every failure, so the loop and the audit keep the same actions.
- **No building on a regression:** `regressed` lists checks that passed in the previous round and fail now; the next repair starts from the image the last repair edited and retries its focus with that image's verdicts (`start_review`). A restart from the clean source re-applies every requested change. Each focus gets one try, so set `max_repairs` to at least the number of failures.
- **Checks can depend on each other:** a brief criterion may list `depends_on`; a check whose prerequisite fails is marked `blocked by <ID>` by the reviewer, listed in `blocked`, and never chosen as the focus. Unknown, repeated, self or circular links are refused (exit 2).
- **Reviewers reread the whole request** after the checks: in the prompt-lab runs a sphere "hanging" came out resting on a pedestal while every check passed.
- **Prompt and repair rules from the experiments and guides:** see the reference updates (reference images leak traits, edits spill onto attached parts, numbers in prompts are approximate, transparency and character-anchor prompts, API mask limits, reviewer vision limits).

## 2.18.0-local.1 (2026-10-20)

Four upgrades from a research pass on defect localization (LEGION, RichHF), region repair (libcom-style harmonization), and image token costs (Claude vision docs). None adds a dependency.

- **`studio_state.py blend --base B --patch P --mask M --out F [--at X,Y] [--feather 8] [--no-match]`:** pastes a repair patch through its mask, shifts the patch's color to match the ring of pixels just outside the mask (gain 0.8-1.25 per channel), feathers only the band outside the mask (the mask itself is always fully replaced), keeps a transparent base's alpha, refuses 16-bit files, and prints the changed area for `edit-check`. A generated patch that came back 40 levels lighter now lands within 3.
- **Agent boxes must locate the problem:** `defect add --source agent` refuses a box over 25% of the image unless `--wide` marks a whole-image problem; the hunter keeps boxes under a quarter of the image and writes "whole image" for overall softness or a color cast.
- **`mac_vision.py hands IN`:** Apple Vision boxes every hand with the number of its 21 joints it saw (no download). The hunt saves each box as `hand-N.png` so every hand is checked at 100%; a found hand is never a pass.
- **Token budget:** `prepare-review` tiles are at least 3x2 and at most about 1024 px a side up to 5x5 tiles (a 3840x2161 image now gives 12 tiles of about 990x750 instead of 16), and `gray.png` is at most 1024 px. The main chat opens only the map, the thumbnail, and the `edit-check` view.

## 2.17.0-local.1 (2026-10-20)

Rule for every straight sword: a red line from the pommel to the tip is the axis, and the blade's own spine must run along it.

- **`axis-check` traces the blade from the pixels:** it follows the blade between the last two points, outlines its edges (cyan) and spine (yellow) in the guide, and draws the red pommel-to-tip line. It fails when a point or the spine is farther from the line than 0.4 of the blade width, capped at 3% of the sword length (`--max-offset PX` overrides) or the spine tilts more than `--max-bend` degrees (now 2 by default). Two points are enough when the blade traces; otherwise it exits 2 instead of passing unchecked. `--guide` may not overwrite `--image`. Segment angles between close points are gone: on the user's straight Canva sword they reported false bends of 9 and 19 degrees; the new check passes it (spine at most 24 px off a 67 px blade, 0.9 degrees) and flags v51's hilt sitting about 25 px left of the blade axis.
- Straight-prop review now requires independent final-pixel landmarks, including the blade base and actual tip, checked with `axis-check`; a guide or numeric pass alone is not evidence. Hidden or ambiguous landmarks stay uncertain.
- Repair preserves the accepted long blade and protected cards/text, patches the short grip/pommel/hand region, and repeats measurement after compositing.
- Scope straightness to intended straight parts: preserve curved bows/blades and angled gun grips/stocks.

## 2.16.0-local.1 (2026-10-19)

A repeated generator error: a sword bent where the hand holds it (pommel to crossguard 42 degrees, blade 59 degrees). Generators draw the grip and the blade separately across the hand.

- **`studio_state.py axis-check --image F --points X,Y X,Y X,Y [--guide out.png]`:** angles of each segment of a rigid object, the bend (exit 1 above `--max-bend`, 3 degrees by default), where each point belongs on the longest segment's line, and a guide image of that line. On the sword it measured a 16.9 degree bend and placed the pommel at 94,314 instead of 25,355.
- **Hunt:** intended straight parts (straight swords, spears, staffs, gun barrels) must be one straight line through any hand or occlusion; the hunter reports their points for `axis-check`.
- **Prompting and repair:** describe a long prop as one straight object with its angle and attach the guide; image-repair repaints only the grip, pommel, and hand along the guide and checks again.

## 2.15.0-local.1 (2026-10-19)

Free tools already on the Mac, tested on the Jadebound banner, the Unbound poster, and a card pack.

- **`image-verify/scripts/mac_vision.py`** (Apple Vision, no download; built once with `swiftc` in about 2 s):
  - `cutout IN OUTDIR [--point X Y]`: subject cutout and masks in about 0.5 s. On painted game art it kept the subject cleanly where rembg's `isnet-anime` failed.
  - `ocr IN [--expect TEXT ...]`: reads every text line with boxes in about 0.3 s ("JADEBOUND", "5000+", "FOLLOWERS" at confidence 1.0) and exits 1 naming any expected text that is missing or misspelled ("5,000+"). The first OCR run on a machine waited 51 minutes while macOS prepared its model; the script now gives up after `--timeout` (180 s).
- **Cutouts:** Apple Vision first; rembg `birefnet-general-lite` (213 MB) when edges matter or off macOS; `isnet-anime` only for flat anime on a plain backdrop; `birefnet-general` (927 MB) dropped.
- **Text checks:** image-create and image-verify check finished text with `ocr --expect` before a person looks.

## 2.14.0-local.1 (2026-10-19)

From a comparison with the upstream image-reconstruction and image-loop repositories (ours already carries every upstream file, with fixes); only prompting lessons were missing.

- **Wording rules** in prompt-blocks.md: tie each property to a named part, plain words over jargon, bundle compatible changes, and change the method after two failed tries.
- **Mismatch table** in image-inspect's diagnosis.md: what went wrong, what to inspect, and the next action, with text sent to layers and local edits to masks.

## 2.13.1-local.1 (2026-10-19)

- **Parallel patches:** image-repair starts the patches for every confirmed region at the same time (parallel `image_gen.imagegen` calls in one step), waits for all, and composites them one at a time; one image is never split between several editing agents. A generation takes minutes, so three regions now take about the time of one, at no extra model calls.

## 2.13.0-local.1 (2026-10-19)

Fewer model calls. In the Jadebound session 70% of the 148 minutes was model time, about 32 seconds per call over 194 calls, so each step folded into one command saves a call.

- **`studio_state.py prepare-review`:** writes every designer-review view (overlapping tiles named by their corner, edges, gray, thumbnail, lineup) in one call and prints the image size and file list the hunter needs; 0.24 s on the 1672x941 poster. The agent had rebuilt these views by hand about 7 times.
- **`studio_state.py verdict --from verdicts.json`:** records every verdict of a gate run in one call; one bad entry writes nothing.
- **Wording:** the docs, the session card, and script messages say "task" instead of "job" for a unit of the user's work.

## 2.12.0-local.1 (2026-10-19)

From a full read of the same Jadebound session, subagents included (about 50 million tokens, 148 minutes, 70% of it model time on a 100,000-380,000 token context).

- **Assets first (image-create step 2):** list the user's logo files, fonts, SVG icons, approved art, and any script that already renders their text before generating; offer two or three local fonts as text layers instead of generated lettering; when the user rejects something the brand kit prescribes, ask once and update the kit. The session generated its title and flag as pictures although local display fonts, an SVG icon, and a text renderer were in the folder.
- **Exact copy:** every word, number format, and platform name is confirmed once before the first render; the agent had added a comma ("5,000+") the user then had to remove.
- **No idle generations:** a step waits for every generation it started (the session sat idle for 8 minutes); style drafts start in parallel.
- **One fresh reviewer:** each hunt or review uses a fresh reviewer, never one that carried an earlier job (a reused reviewer cost 6 million tokens), and the editor does not reopen the views it handed over.
- **Hands:** the hunt judges how hands look, not only the finger count.
- **Sharpen last:** image-enhance runs only after every repair and layout change.

## 2.11.0-local.1 (2026-10-19)

From the Jadebound "5000+ followers" banner session in Codex: 2 h 28 min, 21 user messages, 14 image generations (7 whole images, 4 of them text or flags drawn as pictures), 78 image views, and about 42 million tokens in the main chat, because the chat had carried every job since Oct 11 (about 227,000 tokens resent per step) and every text or logo change regenerated the whole image.

- **Layers:** `image-create/scripts/compose_layers.py` places the subject cutout, the logo file, and each line of text on the generated background from a `layout.json`. Changing a word, the logo position, or the subject's size is an edit and one run, not a new generation. image-create generates art without text or logos, and image-repair sends such changes to the layout.
- **Style first:** image-create settles the rendering (for example 2D or 2.5D, not a 3D render) from taste notes and approved references before the first full image, or shows two or three small drafts and records the pick.
- **Long chats:** the session card suggests a new chat for a new job when the transcript is over 25 MB; image-create says the same when the chat already handled another job. The skills that load project memory (create, edit-map, enhance, loop, repair, verify) read their files once per chat and open each new result once.

## 2.10.0-local.1 (2026-10-18)

Finding and fixing problems in fewer rounds. In the poster job the user found 11 of 13 defects, 3 of them left by an earlier repair, over 11 versions.

- **Hunt at intake and before delivery:** the designer review makes overlapping 100% tiles named by their corner and hunts with a fixed list (AI slop, broken contours, fragmented detail, leftovers of removed objects, seams, specks, style breaks, small content, frame, the user's past complaints). In Claude Code the new `image-hunter` agent does it in its own context and returns one table, so the main chat does not load the tiles; other hosts get the same instructions in `designer-review.md`.
- **`studio_state.py map`:** draws every open defect on one image, so the user confirms or rejects all findings in one round. Agent findings are recorded with `defect add --source agent`.
- **`studio_state.py edit-check`:** after each patch, counts changed pixels outside the edit box (exit 1 if any) and writes one before | after | changed-pixels view with a 24 px ring, the only image a repair round opens. On the real poster it showed the D12 repair had changed 16,627 pixels outside its box, up to the hair.
- **Measured on poster v1:** a blind hunt found 13 other problems but none of the 4 the user had found there (whole-image softness, soft inset images, uneven hat trim, halo behind a horn). Given the user's past complaints as lessons, it found the soft inset image and the stepped trim beside the deadline, but still missed the whole-image softness and the halo. The hunt is a first pass, the user's lessons make it better, and the user still makes the final call.
- **Triage and batches:** six or more high or medium problems, or whole-image softness, lead to an offer to regenerate the whole image before patching; confirmed problems are fixed in one batch and gated once.

## 2.9.3-local.1 (2026-10-18)

Fixes from running every documented tool command on this Mac (ImageMagick, Upscayl with all 7 models, Real-ESRGAN, rembg, Potrace, cwebp, sips, every bundled script, both hooks).

- **Upscale:** the Real-ESRGAN link points to the release zip that includes models (the v0.2.0 zip has none, and the binary crashes without them); `upscayl-standard-4x` and `realesrgan-x4plus` are noted as the same weights; `remacri-4x` is noted to shift color on some images, so it is always trialled against `digital-art-4x`; the SKILL example uses the macOS app path for `upscayl-bin` and resizes by width.
- **Docs:** `+repage` on the lineup view; `mkdir -p r1` before `combine.py` and `advance.py`; the audit's `evidence.json` fields and its `review.json` output listed correctly.

## 2.9.2-local.1 (2026-10-18)

Fixes from researching each tool's official docs and source, every command re-tested on ImageMagick 7.1.2.

- **Repair composite:** the acceptance mask is softened inward only (the old grow-and-blur spread about 14 px past the polygon and could reach the crop edge as a rectangular seam); `-depth 8` is no longer forced, since on a 16-bit source it changed almost every pixel outside the edit; a `compare -metric PDC -read-mask` command proves zero changed pixels outside the mask.
- **Reviewer:** `review.py --crop` attaches 100% crops after the full images, because Codex shrinks attached images and missed small text; the Codex reviewer runs with image generation disabled. image-loop and image-verify name the `image-reviewer` agent and tell the caller to pass it crops.
- **Upscale:** the black-image check uses `-alpha off` (a black result with alpha printed 1 and passed); `realesrgan-ncnn-vulkan` needs `-s` equal to the model's scale; `remacri-4x`, `ultrasharp-4x`, and `ultramix-balanced-4x` are marked non-commercial, with commercial alternatives.
- **Cutouts and logos:** the magenta key gives soft alpha and removes magenta from edge colors (0 pink rim pixels instead of hundreds); logo color masks use `-alpha remove`, so color hidden under transparent areas no longer leaks into a layer; rembg calls must name a model (the default is a 1 GB model with a commercial licence).
- **Codex tools and web export:** `image_gen.imagegen` limits (5 absolute reference paths, one image per call, no size or mask, copy results out of `$CODEX_HOME/generated_images`); `view_image` and Read may shrink images, so crop for true 100%; web export converts non-sRGB masters to sRGB before `-strip`.

## 2.9.1-local.1 (2026-10-18)

Fixes from a full audit of code and docs (3 independent reviewers).

- **Stop hook:** a completion claim followed by a question ("Done. Anything else?") is no longer let through, and a Checked / Not checked / Still failing report excuses a claim only when it names something not checked or still failing ("Still failing: none" counts as a claim).
- **Store:** commands that rewrite a store (approve, defect, gate, verdict) take a file lock, so parallel verdicts no longer overwrite each other (seen in the poster job). The gate decodes the deliverable once instead of once per defect. `taste add --brand B --deliverable N` keeps the deliverable link. Leftover `masters` writes removed.
- **Hooks:** fall back to `python` when `python3` is missing.
- **Docs:** the designer review runs on a first draft and before delivery, not every repair round; taste and lessons recorded without a store are read with `taste list` / `lesson list`; independent review is "when available" and `verdict --reviewer independent` is documented; the multi-chat repair-history template (duplicated by the store) and restated rules are removed; Codex `transparent_background` is preferred over a magenta key; image-inspiration records the person's pick as taste; several stop rules, exit codes, link labels, and "master" wordings corrected.

## 2.9.0-local.1 (2026-10-18)

Fixes found by reading the real poster job (13 defects, 16 gate runs).

- **gate:** a resolved defect whose pixels are identical to an earlier passing run keeps that verdict ("unchanged since run ..."). The old 100% crop is decoded and its pixels hashed, and the earlier verdict must be valid for its own run, so a pass cannot be carried to changed pixels or from a forged verdict. Before, every gate run needed a fresh verdict for every defect ever recorded (12 per run at the end of the job, about 170 in total); now only regions that changed need one. On a copy of the real store all 13 defects carried over.
- **Requested changes:** `defect add --kind scope --quote "the user's words"` is for a change the user asks for that is not a mistake (in the poster job, "change the deadline to the 25th" was recorded as D13). It no longer requires a lesson, and the gate accepts a visible change of 0.5% of its box instead of 5%, so a small text edit is not failed as "almost nothing changed". Without `--quote` a scope defect is treated like any other, so an agent cannot relabel its own mistake to skip the lesson. An adversarial check (1-pixel changes, other deliverables, mismatched runs, forged or edited old verdicts and crops) found no way to carry a pass to changed pixels.

## 2.8.0-local.1 (2026-10-18)

- **image-verify:** new brand kit: `brand set --brand B --color NAME=#RRGGBB[:role] --font ROLE=Family --logo FILE --ref FILE=role --do T --dont T [--remove KEY]` and `brand show`. It keeps exact values in `~/.image-studio/brands/<brand>/brand.json` with the hash of the logo and each approved reference; `brand show` flags a missing or changed file, and the session-start card shows a one-line summary. Approved references and files the user sends are the only existing images an agent may use; the logo is composited from its file, never redrawn. The style block in image-create's `prompt-blocks.md` is filled from it.
- **Not added:** a pixel defect scanner adapted from the owner's video tool. Measured on the owner's real poster store at the v9 stage (each reported crop D3-D12 against the same box in v9), its blown-highlight, speckle, sharpness (high-frequency detail over contrast), and muddiness numbers did not separate rejected from fixed regions (D4 "whole poster soft": 0.096 vs 0.092; an independent gradient measure gave 0.033 vs 0.031), and an 8x5 low-detail tile map flagged the then-open D12 region together with 3 unrelated dark edge tiles among its 5 lowest. The designer review and the gate cover these defects instead.
- **Language:** docs, help, and examples are English; Vietnamese stays only where it is functional (message patterns that recognize the owner's Vietnamese completion claims, praise, and negations) and is labelled as such.

## 2.7.0-local.1 (2026-10-18)

Prompt blocks and a designer review, adapted from the owner's video/banner tool. Docs only.

- **image-create:** new `references/prompt-blocks.md`: one style block with measured values (palette hex, light direction, view) pasted at the start of every prompt in a job, one item per image with empty space for text or a logo added later, a background rule by asset type (flat magenta #FF00FF for cutouts, black for glow effects), reference roles, and a check after generating.
- **image-repair:** `repair-and-composite.md` adds the numbered region-edit prompt ("keep everything, change only these N things", subjects described by position), a one-region-per-turn fallback, and a reminder that generators often redraw the whole image.
- **image-verify:** new `references/designer-review.md`, used before showing a new or regenerated image and before delivery: 6 tiles at 100%, 4 edge strips, a grayscale view, a 120 px thumbnail, a lineup next to the approved version (all `magick` commands tested), checks for two drawing styles in one image, soft or damaged areas, anatomy, edges, color and light; problems first in a severity table, no praise. image-loop's self-check uses it.

## 2.6.0-local.1 (2026-10-18)

Learning the user's taste, not only their complaints.

- **image-verify:** new `taste add --note --aspect [--quote] [--deliverable] [--brand]` and `taste list [--brand]`. When the user approves or praises a result, the agent records what they liked; notes are kept per brand in `~/.image-studio/brands/<brand>/taste.jsonl` (general ones in `taste.jsonl`). The session-start card and `brief` show the 6 newest notes (brand and general merged, newest first, exact repeats shown once) under "Your taste"; the card also reminds the agent to record praise.
- **lessons:** `lesson add --worked` records the method that worked after one failed twice; the card shows it.
- **image-create, image-repair, image-verify, image-loop:** one line each on when to record taste or a working method. Nothing becomes a rule without `pref add --confirmed` after the user agrees.
- Measured on a copy of a real store: with 6 taste notes and 5 lessons the session card grows from about 250 to about 600 tokens, once per session; each `taste add` takes about 0.04 s.

## 2.5.0-local.1 (2026-10-18)

Learning from mistakes across jobs, kept small.

- **image-verify:** new `lesson add --mistake --cause --check [--defect D<n>] [--kind] [--brand]` and `lesson list [--brand]`. Lessons live in `~/.image-studio/lessons.jsonl` and are shared by every job.
- A defect the user reports on a deliverable that had already passed the gate is marked as a miss after delivery; the gate fails until a lesson is linked to it.
- Until that lesson exists, the deliverable also counts as not passed for the session-start card and the Stop hook. Lessons are appended under a file lock, so parallel agents do not lose one.
- The session-start card and `brief` show up to 5 lessons, ranked by same brand, then the kinds of the open defects, then newest.
- When the same kind of mistake has a lesson in 2 or more jobs of a brand, `lesson add` tells the agent once to ask the user whether to make it a preference (not for kind `other`, and not when a brand preference already has that check); it becomes a rule only with `pref add --confirmed` after the user agrees.

## 2.4.3-local.1 (2026-10-18)

Docs only: large reference files are split so an agent reads only the part it needs. No text was dropped.

- **image-enhance:** `recipes.md` (19.6 KB) keeps the upscaling recipes and measurements (8 KB); background removal and cutout edges moved to `cutouts.md`, logo to vector to `logo-vector.md`, web export to `web-export.md`.
- **image-repair:** the quick preflight is `references/preflight.md` (1 KB), read before the first repair on a machine or in a new chat; `tool-readiness.md` keeps full setup. Subject-specific checks (portraits, products, logos, surfaces, web heroes) moved from `repair-and-composite.md` to `subject-checks.md`.

## 2.4.2-local.1 (2026-10-18)

Docs only, from a full markdown audit (43 files: 0 broken links or anchors).

- **image-repair:** the logo exception no longer reads as permission to look for logo art on disk: existing pixels come only from a file the user supplied. 200% crops only when 100% is unclear; "three repairs after the first candidate" matches the controller.
- **All skills:** the memory step uses the full `python3 <skills>/image-verify/scripts/studio_state.py brief` command; exit codes and decision lists match `review.py` and `audit_candidate.py` (`stop_invalid_review`, `stop_provider`, `stop_budget`); image-inspect and image-edit-map have stop conditions; image-loop, image-inspiration, and image-reconstruction say Claude Code has no built-in image generator; official tool links added (ImageMagick, Upscayl, Real-ESRGAN-ncnn-vulkan, uv).
- **project-memory.md:** ZIP defects need a single-image ZIP; the Stop hook also passes Checked / Not checked / Still failing reports.

## 2.4.1-local.1 (2026-10-18)

- **image-enhance, image-loop, image-edit-map:** each SKILL.md is a checklist of about 4 KB; image-edit-map's controls, commands, preservation rules, and tool notes moved to `references/workflow.md`. image-loop's invocation syntax and prompt pattern moved to `references/prompts-and-invoke.md`; the transparent-image metrics of `compare_display.py` are explained in image-enhance's `recipes.md`. The descriptions of the six advanced skills are shorter, so less text is always loaded. `candidate-audit.md` is 6 KB instead of 9 KB.
- **Tools:** the docs give the real Codex image tool arguments (`image_gen.imagegen` with `prompt`, `referenced_image_paths`, `transparent_background`; no size argument, so resize with `magick`), `view_image` with `detail: "original"` for 100% pixels, and say that Claude Code has no built-in image generator (use a configured image tool or hand back the prompt).
- **hooks:** the session-start card has a hard 2,400-character cap that still lists every open defect ID; session pointers record the folder the session started from, and pointers from before this version or from a plugin-development repo below the project are ignored; "xong đợt này ..." / "done with this step" no longer count as completion claims.
- **Cleanup:** unused imports and an unused variable removed.

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
