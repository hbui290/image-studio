# Quick preflight

Read by [image-repair](../SKILL.md) before the first repair on a machine or in a new chat. Full setup, tool sources, and moving a job to a new machine: [tool-readiness.md](tool-readiness.md).

1. Source & refs: verify clean source, approved references, and target dimensions.
2. Raster editor: verify ImageMagick (`magick -version`, `magick identify input.png`) or desktop editor for crops, masks, and compositing.
3. Generator: Codex `image_gen.imagegen` takes `prompt`, `referenced_image_paths` (crop + references) or `num_last_images_to_include`, and `transparent_background`; it has no size argument, so resize the result with `magick`. Claude Code has no built-in image generator: use an image tool the user configured (MCP), or stop and hand back the prompt.
4. Viewing: Codex `view_image` with `detail: "original"` shows native pixels (100%); Claude Code uses Read. Also check the delivered format on the actual target surface.
5. Missing tools: use existing equivalents or report limits; never substitute whole-image generation for controlled repair.
