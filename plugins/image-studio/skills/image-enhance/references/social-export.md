# Social export

Read by [image-enhance](../SKILL.md) only when the condition named there holds. For responsive web sizes use [web-export.md](web-export.md) instead.

Use `export_social.py` as the last step before posting a finished image to X or listing it as an NFT. It does three things the user would otherwise ask for one at a time: the post size, room around the subject and logo, and removing personal metadata. Run it on the final master after every repair and upscale; it does not improve pixels.

## Presets

| Preset | Size (px) | Aspect |
| --- | --- | --- |
| `x-landscape` | 1600x900 | 16:9 |
| `x-square` | 1080x1080 | 1:1 |
| `x-portrait` | 1080x1350 | 4:5 |
| `nft-portrait` | 1024x1536 | 2:3 |
| `--size WxH` | custom | any |

Source, checked 2026-11-09: X's [creative specs](https://help.x.com/en/business-and-advertising/creative-ad-specifications) list the 16:9, 1:1, 4:5, and 2:3 aspect ratios, PNG or JPEG, and a 5 MB file limit. Those specs are for ads; X publishes no separate pixel size for ordinary posts. The 1600x900 and 1080x1350 sizes are the common post sizes at the official ratios (X's ad sizes are 1920x1080 and 1440x1800), so use `--size` for the larger ones. `nft-portrait` is the 1024x1536 size users asked for, not a marketplace rule; check the marketplace's own page before listing.

## Commands

```bash
python3 <skills>/image-enhance/scripts/export_social.py --in final.png --out post-x.jpg --preset x-landscape \
  --focus 820,240,1480,980 --safe 40,1020,360,1110 --margin 0.04 --report post-x.json
```

Run: `uv run --with pillow python3 <skills>/image-enhance/scripts/export_social.py ...` ([uv](https://docs.astral.sh/uv/)) (fallback: `python3 -m pip install pillow`).

- `--fit cover` (default) crops to fill the frame. The crop is the largest window of the output aspect that holds the whole `--focus` box, centered on it; with no `--focus` it is centered on the image. `--fit pad` keeps the whole image and fills the bars with `--pad-color` (default `#000000`); `--focus` with `--fit pad` exits 2.
- Boxes are `x0,y0,x1,y1` in source pixels, as the image is shown after any EXIF rotation. Use `--focus` for the subject and one `--safe` per logo, text block, or face. To keep a subject off the bottom edge, pass it as a `--safe` box.
- `--margin` is a fraction of the output's short side (0.04 on 1600x900 is 36 px). Every `--safe` box must sit at least that far inside every edge.
- `--out` must end in `.png`, `.jpg`, or `.jpeg`, and its folder must already exist (the same for `--report`). `--format png|jpeg` is optional and must match the extension; `--quality` (default 92) applies to JPEG. Transparency is flattened onto `--pad-color` for JPEG.
- Upscaling prints a warning line; a scale above 4x exits 2. Above 2x, upscale with an AI upscaler first (steps 3 to 5 of [image-enhance](../SKILL.md)), then export.

## Metadata

The output is written from decoded pixels only: no EXIF (including GPS and the embedded thumbnail), XMP, IPTC, JPEG comments, or PNG `tEXt`/`iTXt`/`zTXt` chunks. A color profile is converted to sRGB and then dropped; browsers and X show an untagged image as sRGB. The script prints the names of what the source had (for example `iTXt:Author`, `EXIF:Artist`, `APP1:XMP`), never the values, which can hold emails, account names, or file paths. A PNG text keyword is shown only when it is a standard one (`Title`, `Author`, `Description`, `Copyright`, `Creation Time`, `Software`, `Disclaimer`, `Warning`, `Source`, `Comment`, `XML:com.adobe.xmp`); any other shows as `tEXt:<non-standard keyword>`, since a custom keyword can itself hold personal data. It then re-reads the written file and stops if anything is left.

This is privacy cleanup only. It does not change pixels to hide how an image was made.

The script also checks the output file name: spaces or non-ASCII characters print a suggested ASCII name. It never renames the file.

## Outputs

- The image at `--out`, exactly the preset size.
- Printed summary: size, scale, crop box (source px), focus and safe boxes (output px), and removed metadata names.
- `--report` JSON: `ok`, `input` (`path`, `width`, `height`), `output` (`path`, `width`, `height`, `format`, `bytes`), `preset`, `fit`, `margin`, `crop_box`, `scale`, `pad_offset`, `focus`, `safe_boxes` (each with `source_box`, `output_box`, `distances_px`, `required_px`, `failed_edges`, `ok`), `removed_metadata`, `remaining_metadata`, `suggested_name`, `warnings`, `stop`. Fields appear when they apply; the report is also written on exit 1.

## Stop conditions

- Exit 1, `--focus` does not fit: the subject is wider or taller than any crop at that aspect. Use `--fit pad`, a tighter `--focus`, or a preset whose aspect matches the image. No image is written.
- Exit 1, `--safe` box too close to an edge: the message names the box, its source and output pixels, and each edge that fails. Move the focus, use `--fit pad`, or fix the layout with [image-repair](../../image-repair/SKILL.md). No image is written.
- Exit 1, metadata left in the output: the output is deleted. Report it as a bug; do not post the source instead.
- Exit 2: bad input (missing or unreadable file, missing `--out` or `--report` folder, bad box, size, margin, color, or format, an extension that does not match `--format`, `--focus` with `--fit pad`), a `--report` that cannot be written, or an upscale above 4x.
- An output over 5 MB for an `x-` preset prints a warning: use JPEG or a lower `--quality`.
