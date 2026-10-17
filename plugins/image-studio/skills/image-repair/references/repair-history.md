# Repair history

Use this task-level record when an image fix spans review rounds, turns, or chats, or when the user reports a missed defect. Keep it beside the image and round folders so the next session can continue from evidence instead of memory.

When the project has a `.image-studio/` store ([project memory](../../image-verify/references/project-memory.md)), `defects.jsonl` is the source of truth for defect IDs, boxes, and status. Use its `D<n>` IDs here instead of inventing new ones, record a new defect with `studio_state.py defect add` first, and change status only with `defect close`. This file then keeps only the narrative: attempts, rejected methods, evidence, and the next method.

## Before each attempt

1. Read this file and the latest review/audit outputs.
2. Start from the frozen approved source or last accepted candidate. Never branch from a rejected edit unless the history explicitly approves it as the new source.
3. Keep defect IDs stable (the store's `D<n>` IDs when a store exists). Record source filename and SHA-256, source-coordinate bounds, the visible evidence, protected neighbors, and the exact acceptance condition.
4. Check the rejected-method notes. If the same defect returned, change the operation, mask, reference, or source; do not just strengthen the same prompt.

## After each review

Append a dated round with the candidate, tool actually used, changed region/mask, pass/fail/uncertain verdict per defect, crop or audit evidence, rejected reason, and the next method. Mark a defect resolved (with `defect close` when a store exists) only after inspecting the exact exported artifact at native and delivery size. Carry unresolved items forward verbatim.

For object removal, record separate checks for the recognizable face/silhouette and its residue: frame edges and corners, straight border strokes, glow or color spill, shadows, and fragments visible at occlusion boundaries. A prior pass that checked only for a recognizable whole object is insufficient; add a new stable defect/check for anything later found and inspect it at 100% and 200% before closing it.

## Entry template

```text
## YYYY-MM-DD — round N
- Frozen source: <path>; SHA-256: <hash>
- Defects: <stable IDs (store D<n> when present) and source-coordinate bounds>
- Protected details: <shapes, text, objects, pixels>
- Attempt: <operation/tool and candidate path>
- Review: <pass/fail/uncertain per ID, with crop or audit evidence>
- Rejected because: <specific visible failure, or none>
- Next method: <one changed method, or resolved>
- Final artifact checked: <path/hash, native + delivery-size result>
```

Do not describe a failure as resolved because a prompt ran, the file opened, or an audit passed. The record is a human-readable handoff, not model training or automatic learning.
