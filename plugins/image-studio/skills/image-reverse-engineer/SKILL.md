---
name: image-reverse-engineer
description: Extract a supplied image into a structured image-spec JSON file (typography, palette, grading, composition, numbered elements, inferred layers, lighting) with an evidence basis and confidence for each value, without editing anything. Use when asked to "reverse engineer this image", "break this image down", "extract the design as JSON", or "describe this image's style". Not for planning an edit of the image (image-edit-map), rebuilding or remixing it (image-reconstruction), or mixing several references (image-inspiration).
---

# Image reverse engineering

Turn one image into a reusable visual specification. This is read-only analysis: it does not generate or change any image.

## When to use this skill or a sibling

- **image-reverse-engineer (this skill):** the user wants a JSON or written breakdown of an image and nothing else.
- **[image-edit-map](../image-edit-map/SKILL.md):** the user wants to change parts of the image in place and pick targets from a numbered map. It uses the same protocol and schema.
- **[image-reconstruction](../image-reconstruction/SKILL.md):** the user wants a new image rebuilt or remixed from one reference, using a full part inventory and a compiled prompt.
- **[image-inspiration](../image-inspiration/SKILL.md):** several references should be combined into new variants.
- **[image-create](../image-create/SKILL.md):** a new image from a brief, with no breakdown needed.

## Steps

1. Get the image. If none is attached, ask for it. Do not invent its contents.
2. Read the file's real width and height with a file tool (for example Pillow or `magick identify`). Do not trust dimensions from a resized preview. If no file tool is available, record the dimensions as unknown.
3. Follow the [reverse-engineering protocol](../image-edit-map/references/reverse-engineer.md): assign the image ID `A` (then `B`, ...), sections `A:S1`, `A:S2`, and elements `A:1`, `A:2` as described in the [mapping protocol](../image-edit-map/references/mapping-and-prompts.md). Set `mode` to `reverse_engineer`. Each image needs a `picture_types` record.
4. Give every extracted value an observation object with `value`, `basis`, `confidence`, and `note`. Unknown values are `null` with `basis: "unknown"`. An absent category is `[]`. Fill `locked_properties` only from explicit user constraints; otherwise use `[]`.
5. Save the result as `image-spec.json` in the working folder. It must match [image-spec.schema.json](../image-edit-map/references/image-spec.schema.json) (`schema_version` `1.0`).
6. Validate it (see below). Fix every reported error and run the command again until it passes.
7. Return the JSON file path and a short readable summary, unless the user asked for JSON only. Then offer a next step: inspect an element, plan an edit with image-edit-map, or rebuild with image-reconstruction. Do not start an edit or a generation on your own.

## Validate

```sh
python3 <skills>/image-edit-map/scripts/validate_spec.py image-spec.json --image <source image>
```

Add `--image-id B` when the file describes more than one image. The script checks the schema, bounding boxes, ID uniqueness, cross-references, and (with `--image`) that the reported width and height match the decoded file.

| Exit code | Meaning |
| --- | --- |
| 0 | Passed. Prints `PASS: ...`. Visual accuracy is not checked. |
| 1 | The spec is invalid or the dimensions do not match. Each problem is printed on its own line. |
| 2 | A file is missing or unreadable, the JSON cannot be parsed, or a dependency is missing. |

A passing result does not prove that the descriptions are correct. Look at the image again to check them.

## Limits

A flat image does not reveal its original prompt, exact font family, editable layers, hidden or covered content, or exact grading settings. Report these as estimates or unknowns. The `reconstruction` brief in the spec is a newly written approximation, never "the original prompt". The [example spec](../image-edit-map/examples/image-spec.example.json) is synthetic; never copy its values.

## Running the scripts

In commands, `<skills>` means the folder that holds the Image Studio skill folders, which is this skill's parent folder (the host shows the skill's path when it loads); run commands from your working folder. The validator needs Python 3 with jsonschema, and Pillow for `--image`: prefix the command with `uv run --with pillow --with jsonschema` ([uv](https://docs.astral.sh/uv/)), or install them with `python3 -m pip install pillow jsonschema`.
