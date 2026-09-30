# Bounded review and handoff

Use this reference for crowded scenes, identity-critical edits, multiple candidates, or more than one repair round. A simple crop or export does not need a formal review ledger. This workflow needs no additional skill, model, schema package, or service.

## Before generation

Write a compact check list against the untouched source and approved references. Give each required visual change or preservation rule a stable ID and a visible pass condition. Record technical file checks separately. For example:

| ID | Kind | Requirement | Observable check |
| --- | --- | --- | --- |
| R1 | Requested | Replace the broken mug handle | One attached handle with the source's perspective and light direction at 100% view |
| P1 | Protected | Keep the adjacent hand | Same pose, fingers, and overlap as the source; zero changed pixels outside the final acceptance mask if exact preservation is required |
| F1 | File | Deliver the agreed canvas | Decode the exported file and read its actual dimensions and format |

Do not treat a pleasing overall image as compensation for a failed required item. A reference only controls the properties assigned to it. If the named target does not exist in the source, verify the user's intent before generating a purported fix. When comparing alternatives, use the same crop and display size; judge visible fit before model or provider reputation.

## Review each candidate

1. Save the clean source, candidate, final acceptance mask when used, and the exact prompt if available. Record the actual tool and model only when exposed by the tool. Do not review an annotated object map as the clean source.
2. Inspect every ID at native pixels and the whole image at delivery size. Mark each `pass`, `fail`, or `uncertain` and name the observed evidence or missing evidence. Check neighboring regions and all protected IDs again after each repair.
3. Check that every required ID appears exactly once in the review; missing, duplicate, or invented IDs invalidate that review. Check an object's existence before its dependent attributes: a missing mug cannot pass a handle-shape check. Run objective file checks before spending a model review, and run pixel checks separately. A vision reviewer can judge visible geometry and identity but cannot prove byte-level preservation, exact fonts, or invisible layer structure. An independent image-capable reviewer is optional for consequential or crowded edits; record whether the review was independent or by the editing agent.
4. Accept only when all required IDs pass and the exported asset passes its delivery checks. If a required result is uncertain, inspect more closely or hold it for the user's judgment. Keep advisory findings separate from required checks. A model's approval is not the user's approval.

If an independent reviewer is available, give it the clean source, clean candidate, approved reference roles, and the unchanged criterion list. Keep candidate names neutral and withhold the editor's preferred outcome. Ask for one `pass`, `fail`, or `uncertain` verdict per ID with a visible reason and a minimal fix for failures; do not let the reviewer add new requirements. If it cannot inspect the actual images, treat its response as unverified text rather than an image review. A reviewer can miss tiny lettering or spatial relationships, so inspect disputed regions yourself and keep uncertainty visible.

## Stop or repair

Set a repair limit before expensive generation; three targeted repairs is a reasonable default when no smaller budget is specified. Repair only a named failure and restart from the last accepted clean source or candidate, not a chain of rejected outputs. After each repair, review the complete original check list rather than only the repaired area. Stop if the same failure persists across two repair rounds, a required reference is missing, the provider fails, or the agreed budget is exhausted. Keep the best candidate that satisfies all protected checks; otherwise retain the source and report the unresolved defect. When comparing multiple candidates, first reject those failing required checks; compare aesthetics only among eligible candidates at equal display size. Keep the rejected attempts and call counts in the record.

For handoff to another agent or machine, record source version and dimensions, approved references, target IDs and source-pixel coordinates, crop, generation-mask polarity if used, final acceptance mask, tool actually used, candidate chosen or rejected, and the status of each required ID. Hash the source and accepted candidate when exact version matching matters. Coordinates and masks from one source version must not be silently reused on another.

## Related approaches

This review method draws on the independent, bounded checks in [Image Loop](https://github.com/codejunkie99/image-loop/blob/main/skills/image-loop/SKILL.md), the addressable elements in [Image Edit Map](https://github.com/codejunkie99/image-loop/blob/main/skills/image-edit-map/SKILL.md), and the explicit reject/hold distinction in [Visual Design Kit](https://github.com/newmindsgroup/visual-design-kit/blob/main/plugins/visual-design-studio/library/templates/media-quality-rubric.md). The instructions above remain tool-independent. The optional [candidate audit](candidate-audit.md) adds this plugin's own source-pixel and mask checks; do not imply it ran merely because it is bundled.
