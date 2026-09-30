# Accept or reject a candidate

Use this before accepting any edited or generated image, together with [review-loop.md](review-loop.md) for multi-round work and [candidate-audit.md](candidate-audit.md) for exact pixel checks.

1. **Identity and meaning:** Compare protected faces, products, animals, hands, clothing, marks, logos, labels, and object count against approved sources. Reject identity drift, duplicated items, misspelled text, and changed meaning.
2. **Local craft:** At 100% scale, check geometry, perspective, repeated textures, halos, seams, smeared edges, and inconsistent grain or line weight. For connected objects, follow supports, joints, occlusion, and usable paths across the crop boundary.
3. **Whole composition:** Inspect the final crop at every relevant target size. Confirm focal point, negative space, legibility, and the relationship between image and overlaid content.
4. **File delivery:** Verify dimensions, orientation, color profile when relevant, transparency, format, decoding, file size, and actual references in the destination. Preserve an editable master when future changes are likely.
5. **Evidence:** State the source, operations, generated regions, rejected candidates that affected the decision, what was visually checked, and what remains unverified. Separate tools actually run from tools merely installed or proposed, and verbatim prompts from reconstructed examples. Distinguish a local preview from a deployed result. Do not present a successful export or build as proof of visual quality.

For a multi-round edit, read [review-loop.md](review-loop.md) before accepting a candidate. Review every required criterion after each repair, including protected content, and record pass, fail, or uncertain with visible evidence. An independent image-capable reviewer can add a second assessment when the stakes justify it; label a self-review honestly. Model review cannot establish exact pixel identity, which requires a deterministic comparison.

When a protected region must remain exact, compare the source and uncompressed composite outside the nonzero final acceptance mask. Investigate every changed pixel there before lossy export; then inspect the exported image visually because compression may change even protected pixels. Check seams both numerically and at 100% view.

If a candidate repeatedly changes protected content, stop rerunning the same full-image prompt. Narrow the crop, strengthen the reference, use a manual edit, or keep the prior version. The correct outcome can be to reject an AI result.
