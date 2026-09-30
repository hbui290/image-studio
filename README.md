# Image Studio

**Fix or create images with AI, change only what you name, and prove the rest stayed the same.**

A plugin of nine skills plus one reviewer agent for Claude Code and Codex. It includes no image model: your agent's image tool draws the pixels, and Image Studio plans the edit, checks the result, and decides whether to accept, repair, or stop.

## Skills

| Skill | Does |
| --- | --- |
| `image-inspect` | Diagnoses defects and numbers repeated objects so you can pick a target |
| `image-edit-map` | Builds a numbered map of elements and plans an edit |
| `image-reverse-engineer` | Extracts typography, palette, composition, and lighting to JSON |
| `image-reconstruction` | Splits a reference into parts to recreate or remix it |
| `image-inspiration` | Mixes several references into traceable directions |
| `image-create` | Generates new images with a role for each reference |
| `image-loop` | Creates or edits, reviews, and repairs up to three times |
| `image-repair` | Fixes one region through a mask and leaves the rest untouched |
| `image-verify` | Reviews each criterion and audits pixels outside the mask |

Agent `image-reviewer` grades a candidate independently, so the editing agent does not grade its own work.

Example: in a picture of ten characters, `/image-repair` fixes the two distorted faces. `image-verify` then confirms that zero pixels changed on the other eight.

## Install

```bash
# Claude Code
claude plugin marketplace add hbui290/image-studio
claude plugin install image-studio@image-studio

# Codex
codex plugin marketplace add hbui290/image-studio
codex plugin add image-studio@image-studio

# Any agent that reads a skills folder
python3 scripts/install.py --to <your-skills-directory>
```

Start a new session afterwards. Use one install method per agent, and remove older copies of the same skills.

## Tools

Install only what the job needs:

| Job | Needs |
| --- | --- |
| Inspect or plan | Nothing extra |
| Crop, mask, composite, export | [ImageMagick](https://imagemagick.org/download/) or any editor with exact pixel placement |
| Redraw a missing detail | An image generator or editor available to your agent, plus the above |
| Check results | Python 3 with [Pillow](https://pypi.org/project/pillow/) and [jsonschema](https://pypi.org/project/jsonschema/) |
| Tiny detail that needs more pixels | Optional: [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) |
| Many objects to select automatically | Optional: [Grounded SAM 2](https://github.com/IDEA-Research/Grounded-SAM-2) |
| Automated vision review through Codex | Optional: [Codex CLI](https://github.com/openai/codex) and a vision model your account can run |

The details and a pre-flight checklist are in [tool readiness](plugins/image-studio/skills/image-repair/references/tool-readiness.md).

## How checking works

1. Every requested change and every protected region gets an ID and a pass condition.
2. A reviewer marks each ID `pass`, `fail`, or `uncertain`. The reviewer can be the `image-reviewer` agent, a Codex vision model, or a person.
3. `audit_candidate.py` compares decoded pixels. A single changed pixel outside the mask rejects the candidate, whatever the reviewer said.
4. A failure produces a repair prompt with exact source coordinates. The loop stops on uncertainty, a repeated failure, or the repair limit.

## Test

```bash
python3 -m pip install pillow jsonschema
python3 -m unittest discover -s tests
```

These offline tests call no model. They check the logic, not image quality.

## Limits

- Vision reviewers can miss small text and fine spatial details.
- A flat image does not reveal its original prompt, fonts, or layers.
- `accepted_by_checks` means the stated checks passed. It is not human approval.

MIT license. See [NOTICE](NOTICE) for sources.
