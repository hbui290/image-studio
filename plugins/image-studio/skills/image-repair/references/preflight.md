# Quick preflight

Read by [image-repair](../SKILL.md) before the first repair on a machine or in a new chat. Full setup, tool sources, and moving a job to a new machine: [tool-readiness.md](tool-readiness.md).

1. Source & refs: verify clean source, approved references, and target dimensions.
2. Raster editor: verify ImageMagick (`magick -version`, `magick identify input.png`) or desktop editor for crops, masks, and compositing.
3. Generator: Codex `image_gen.imagegen` takes `prompt`, `referenced_image_paths` (crop + references; at most 5, absolute paths) or `num_last_images_to_include` (not both), and `transparent_background`; open each reference with `view_image` first. It returns one image per call, has no size or mask argument, and picks its own size: state the aspect ratio in the prompt, pad the context crop near that ratio, and resize the result with `magick`. Copy the result out of `$CODEX_HOME/generated_images` into the job folder. Claude Code has no built-in image generator: use an image tool the user configured (MCP), or stop and hand back the prompt.
4. Viewing: Codex `view_image` shrinks images by default (to 2048 px on the long side); `detail: "original"`, on models that offer it, keeps up to 6000 px and about 10 MP. Claude Code's Read may also shrink large images. To see true 100% pixels, crop the region with `magick` and view the crop. Also check the delivered format on the actual target surface.
5. Missing tools: use existing equivalents or report limits; never substitute whole-image generation for controlled repair.
