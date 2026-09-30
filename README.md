# Image Studio

**Create, edit, repair, and verify images with evidence. Point at the part to change, protect what must stay, and prove it.**

![Version](https://img.shields.io/badge/version-v2.0.0-0B6E75) ![Format](https://img.shields.io/badge/format-Claude%20Code%20%2B%20Codex%20plugin-2D4059)

Image Studio is a plugin of nine agent skills plus one reviewer agent. It combines [image-loop](https://github.com/codejunkie99/image-loop), which covers creating, mapping, mixing, and review loops, with [image-processing-skill](https://github.com/hbui290/image-processing-skill), which covers diagnosis, local repair, and source-pixel audits. It adds the connections between them. It includes no image model: the host agent's image tool makes the pixels, and the scripts check and decide.

## Skills

| Skill | Use it to | Edits pixels? |
| --- | --- | --- |
| [image-inspect](plugins/image-studio/skills/image-inspect/SKILL.md) | Diagnose why an image looks wrong (crop, CSS, compression, missing detail) and map ambiguous targets | No |
| [image-edit-map](plugins/image-studio/skills/image-edit-map/SKILL.md) | Number every element so you can say "change #3", and plan the edit | No |
| [image-reverse-engineer](plugins/image-studio/skills/image-reverse-engineer/SKILL.md) | Extract typography, palette, composition, and lighting to JSON | No |
| [image-reconstruction](plugins/image-studio/skills/image-reconstruction/SKILL.md) | Split a reference into named parts and compile prompts to recreate or remix it | Via host tool |
| [image-inspiration](plugins/image-studio/skills/image-inspiration/SKILL.md) | Mix several references into traceable combinations, in one batch or a judged loop | Via host tool |
| [image-create](plugins/image-studio/skills/image-create/SKILL.md) | Generate new art where each reference has a declared role | Via host tool |
| [image-loop](plugins/image-studio/skills/image-loop/SKILL.md) | Create or edit, then run an independent review and a bounded number of repairs | Via host tool |
| [image-repair](plugins/image-studio/skills/image-repair/SKILL.md) | Fix one defect locally and composite only approved pixels through a mask | Via host tool |
| [image-verify](plugins/image-studio/skills/image-verify/SKILL.md) | Check a candidate criterion by criterion, and audit exact pixels outside the mask | No |

Agent: [image-reviewer](plugins/image-studio/agents/image-reviewer.md) (Claude Code) inspects the source and candidate independently and writes one `pass`/`fail`/`uncertain` verdict per check ID.

## What the combination adds

The two source projects checked different things. image-loop asked a vision model whether the image *looks* right. image-processing-skill counted pixels to prove nothing *outside* the edit changed. Image Studio runs both on the same check IDs:

```
contract.json ──contract_to_brief.py──► brief.json
     │                                      │
     │                   review (pick one): image-reviewer agent │ Codex vision model │ a person
     │                                      ▼
     └──────────► audit_candidate.py ◄── report.json
                        │
   accepted_by_checks │ repair + repair-prompt.txt (with source-pixel boxes) │ hold │ reject │ stop
```

- A vision `pass` cannot override a pixel failure. One changed pixel outside the mask still rejects the candidate.
- If a protected object inside the editable area was repainted, the candidate is held for inspection, even when the reviewer said `pass`.
- `review.py --report` runs image-loop's controller on a report from the Claude agent or a person, so the loop works without Codex.

## Typical jobs

1. **Fix one detail and keep everything else.** `/image-repair` → the host image tool edits a crop → composite through a mask → `/image-verify` with the audit.
2. **Make a new graphic that must meet a brief.** `/image-loop Create a launch poster ...` → review → up to three targeted repairs.
3. **Explore directions from references.** `/image-inspiration Mix these three references into four directions --mode batch --judge human`.
4. **Understand a reference.** `/image-reverse-engineer` for JSON, or `/image-reconstruction` to rebuild it.

In Codex, use `$image-repair`, `$image-loop`, and so on.

## Install

**Claude Code**

```bash
claude plugin marketplace add hbui290/image-studio
claude plugin install image-studio@image-studio
```

**Codex**

```bash
codex plugin marketplace add hbui290/image-studio
codex plugin add image-studio@image-studio
```

Start a new session afterwards. Opening this repository in Claude Code also exposes the skills through `.claude/skills/`.

**Standalone skills folder** (any agent that reads a skills directory):

```bash
python3 scripts/install.py --to ~/.claude/skills   # or ~/.codex/skills
```

The installer copies all nine skill folders together, because they link to each other's references. It refuses to overwrite existing skills unless you pass `--replace`. Choose one method per agent. Installing both the plugin and the standalone folders duplicates the skills. If the older `image-processing` skill is installed, remove it first, because its instructions now live in `image-inspect`, `image-create`, `image-repair`, and `image-verify`.

## Requirements

- An image-capable host agent for generation or editing.
- Python 3 with Pillow for file and pixel checks, plus jsonschema for image-loop, edit-map, and inspiration scripts: `uv run --with pillow --with jsonschema python ...`.
- Optional: an authenticated Codex CLI and a vision model for `review.py --model`. That route consumes account usage.
- Optional editing tools such as ImageMagick, Real-ESRGAN, or Grounded SAM 2. See [tool readiness](plugins/image-studio/skills/image-repair/references/tool-readiness.md).

## Validate

```bash
uv run --with pillow --with jsonschema python -m unittest discover -s tests -v
claude plugin validate --strict plugins/image-studio
claude plugin validate --strict .
```

The 54 offline tests cover the review controller, inspiration planning, the pixel audit (including the protected-target, transparency, and feathered-mask rules), the contract-to-review bridge end to end with a stub Codex, package links, manifests, and the standalone installer. They do not call a model and do not prove visual quality. The [live examples](examples/RESULTS.md) show real generation and review runs.

## Limits

- Vision reviewers miss small text and precise spatial relationships. Uncertain results stop the loop instead of passing.
- A flat image does not reveal its original prompt, exact fonts, layers, or grading settings.
- `accepted_by_checks` means the stated checks passed. It is not human approval.

## Origins and license

MIT. See [NOTICE](NOTICE) for which files came from which project. The prompt-lab article collection (about 445 MB) stays in [image-loop](https://github.com/codejunkie99/image-loop/tree/main/prompt-lab). The [prompt library](prompts/README.md) and examples are included here.
