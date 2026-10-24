# Construction reference

Read by [image-repair](../../image-repair/SKILL.md), [image-loop](../../image-loop/SKILL.md), and [image-create](../../image-create/SKILL.md) before drawing or fixing an object whose shape follows from how it is physically built. Patching one stroke at a time cannot fix an object you do not understand: find out how it works, confirm that with the user, then rebuild the whole part.

## When

- Before editing an object whose shape depends on a physical mechanism (a tear, fold, or peel; a grip on a tool or weapon; stacked or fanned cards; worn armor or straps; a hinge; cloth drape; a liquid) when you cannot state its construction in one sentence.
- When the user rejects the same region a second time: `defect add` prints "Repeat: this region was already reported (D<n>)" and the gate will not pass until a construction rule and a lesson are recorded.
- When the user asks whether you researched references.

## Steps

1. **Write the construction as a hypothesis**, one sentence that names every part and how they connect (for example "the torn top strip stays attached at one end; its length equals the tear edge; the front and back foil layers separate at the tear").
2. **Find 3-5 real photos of the same action from a similar viewing angle.** Codex: the web tool's image search; Claude Code: WebSearch and WebFetch; or any search skill the host has. Reject a reference that shows a different mechanism (a back-seam peel when the user means a top tear) and say why. A drawing or render is weaker evidence than a photo.
3. **Show the user a small reference board** (each file path with one line on what it proves) and wait for confirmation before generating anything. When the user explains the mechanism in words, those words are the authority: record them with `--quote`, and correct the hypothesis to match.
4. **Record the rule** against the defect, with the reference files or the user's words:
   ```bash
   python3 <skills>/image-verify/scripts/studio_state.py construction add --defect D<n> --object "booster pack" \
     --rule "torn top strip stays attached at one end; its length equals the tear edge" --ref refs/tear-1.jpg --ref refs/tear-2.jpg
   ```
   Use `--quote "the user's words"` instead of, or with, `--ref`. Each `--ref` must be a readable image; its path and sha256 are stored. The session-start card and `brief` show the newest rules. For a repeat, also run `lesson add --defect D<n>` (what went wrong, why, what to check next time).
5. **Rebuild the whole sub-assembly from the rule** (the whole torn edge with its strip, the whole hand with its grip), not the one stroke the user pointed at. Before delivery, check every clause of the rule on the final pixels and name what you saw for each one.

## Rules

- References are for understanding only. Never composite, trace, or paste pixels from them; pixels still come only from the user's files, approved references, and the logo in `brand show` ([brand kit](project-memory.md#brand-kit)).
- **Stop rule:** if two rebuilds after a confirmed rule still fail, stop and ask the user. Do not keep regenerating.
