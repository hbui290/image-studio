# Tool readiness and portable setup

Use this reference before editing on a new or reinstalled machine, or when a new agent inherits the job. The skill is an operating method, not a bundle of executables, model weights, credentials, or source images. Count capabilities first, then use tools already present or set up only what is missing and authorized.

## How many tools are needed?

Count **image-editing capabilities**, not app names. A viewer is required for review but is outside this count. A single capable application may satisfy several rows.

| Task | Editing capabilities | What must be available | Example |
| --- | ---: | --- | --- |
| Assess only | 0 | Open the source at native pixels and view its delivered crop | Image viewer or browser |
| Crop, mask, retouch, or export without new semantic detail | 1 | Pixel-addressed raster editing and the target-format export | ImageMagick `magick` or a capable desktop editor |
| Rebuild a missing face, object, or structure, then preserve the rest | 2 | Reference-guided generation or manual drawing **and** controlled compositing | ChatGPT ImageGen + ImageMagick |
| Automatically propose masks for many or tiny objects | +1, only if needed | Detector/segmenter with inspectable output and stable object IDs | Grounded SAM 2; manual object mapping needs no extra tool |
| Add display pixels to a recognizable image | +1, only if needed | Suitable super-resolution model and a before/after comparison | Real-ESRGAN |

For web delivery, also check the real page in a browser and run the project's build when source or assets changed. These are delivery checks, not extra image-editing capabilities. `cwebp` is optional when the raster editor already exports the required WebP. Face restorers, background removers, and inpainting packages are conditional alternatives, not a default install set.

For local repairs with multiple review rounds or exact protected pixels, [the optional candidate audit](../../image-verify/references/candidate-audit.md) validates a structured visual report and measures decoded pixel changes. It needs Python 3 and Pillow only when selected. A separate human or image-capable reviewer still judges visible meaning. These are **review** dependencies, not image-editing capabilities, and no part is installed automatically.

## Tool sources

Use the official project or maintainer source when setup is needed. A repository link identifies the project; it does not prove that its code is installed, compatible with the machine, or already used in a repair.

| Tool | Role | Source |
| --- | --- | --- |
| Host image generator (for example ChatGPT/Codex image generation) | Proposes pixels for missing detail from a crop and references | [OpenAI image generation](https://developers.openai.com/api/docs/guides/tools-image-generation); hosted, so verify access instead of downloading a model |
| ImageMagick `magick` | Exact crops, masks, composites, comparisons, export | [GitHub](https://github.com/ImageMagick/ImageMagick) · [install](https://imagemagick.org/download/) |
| Real-ESRGAN | Super-resolution when recognizable detail needs more pixels | [GitHub](https://github.com/xinntao/Real-ESRGAN) |
| Grounded SAM 2 | Grounded detection plus mask proposals for crowded scenes | [GitHub](https://github.com/IDEA-Research/Grounded-SAM-2) · [install](https://github.com/IDEA-Research/Grounded-SAM-2/blob/main/INSTALL.md) |
| SAM 2 | Segmentation masks | [GitHub](https://github.com/facebookresearch/sam2) |
| `cwebp` / libwebp | WebP encoding when the editor cannot export it | [GitHub](https://github.com/webmproject/libwebp) |

Other conditional examples named in [repair-and-composite.md](repair-and-composite.md): [LaMa](https://github.com/advimman/lama) for inpainting, [CodeFormer](https://github.com/sczhou/CodeFormer) for face restoration, and [Diffusers](https://github.com/huggingface/diffusers) for model-based inpainting. These links are options and provenance, not a command to install the entire list.

## What must travel to a new machine or agent?

- The Image Studio skills: install the `image-studio` plugin, or copy all skill folders with `python3 scripts/install.py --to <skills directory>`. The skills link to each other's `references/`, so copying one `SKILL.md` or one folder alone breaks its detailed instructions. Start a new session and verify that the skills appear in that agent's available-skill list.
- The untouched source, approved identity or product references, and any accepted candidate, mask, editable composite, and delivery file needed to continue a specific job. Record their dimensions and which version is authoritative.
- The task brief: permitted changes, protected regions, target dimensions/formats, actual display surface, and current status. Include exact crop coordinates and mask polarity only when they belong to the transferred source version.
- The chosen tool/model names and versions, how they were accessed, what was actually run, and which outputs passed review. A prompt alone cannot reproduce stochastic generated pixels; preserve accepted candidate files for exact continuation.

## Preflight

1. Locate the source and approved references. Record dimensions, formats, color profiles when relevant, and intended output. If an identity-critical reference is missing, obtain it before drawing that feature.
2. Inventory available capabilities against the table above. For the ImageMagick recipe in [repair-and-composite.md](repair-and-composite.md), run `magick -version`, then `magick identify input.png` on a real task image. Confirm that it reads the input and writes a small sample in the target format. On PowerShell use `Get-Command magick` to locate it; on POSIX shells use `command -v magick`.
3. If pixels must be generated, confirm that the available editor can accept the source crop **and** the approved references and save a candidate. Check tool access and any cost before a generation call; an ordinary prompt interface does not prove image-reference editing is available. If a separate upscaler or segmenter is selected, verify its executable, model weights, hardware support, and a sample result before a long run.
4. Verify native-pixel viewing and, for web images, the actual browser/page. Inspect one crop, its mask, the uncompressed composite, and a delivered-format sample at target size. Confirm dimensions, alpha, decoding, and protected regions.
5. If a needed capability is absent, use an existing equivalent that satisfies the same checks or follow the environment's installation and authorization rules. Record the missing capability and stop before claiming the intended repair is reproducible.

## Setting up an ImageMagick-based composite

ImageMagick is the documented command-line example, not a universal requirement. Follow the [official download instructions](https://imagemagick.org/download/) for the target operating system; verify the installer and package source before running it. On macOS with Homebrew, the official instructions use `brew install imagemagick`. On Windows, they list an official installer and `winget install ImageMagick.Q16`; reopen the terminal after installation and check `magick -version`. On Linux, use the official AppImage or a trusted distribution package that provides ImageMagick 7 and the `magick` command. Check codec support with a real input and sample export; a working command does not guarantee every delegate or format is present.

If an approved desktop editor already supports exact source-pixel crops, a reviewed alpha mask, compositing at a known offset, and lossless review export, use it instead. Translate the [ImageMagick example](repair-and-composite.md) into those operations and document the chosen tool. Do not silently substitute a whole-image generative edit for a controlled final composite.

If the task actually needs super-resolution, consult the [Real-ESRGAN project](https://github.com/xinntao/Real-ESRGAN) for a compatible executable and model weights, then verify the selected model and scale on a small crop. If object proposals would materially help, inspect the [Grounded SAM 2 project](https://github.com/IDEA-Research/Grounded-SAM-2) and its installation requirements before deciding whether the local hardware and environment can run it. Both are optional; neither replaces final mask inspection or compositing.

Face restorers, background removers, inpainting frameworks, and separate encoders are similarly conditional. Obtain current versions, weights, and hardware requirements from the selected project's documentation. Do not assume a global `upscale` wrapper, macOS `sips`, a GPU, a particular Python package, or a proprietary image service exists on the new machine. When no suitable image generator or approved reference is available for missing semantic detail, report that limit instead of presenting an upscale as a complete repair.
