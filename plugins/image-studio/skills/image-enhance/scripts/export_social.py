#!/usr/bin/env python3
"""Export a finished image at a social-post size, check that the subject and safe boxes fit, and strip metadata.

Resizes to a preset (or --size WxH) by cropping (--fit cover) or letterboxing (--fit pad). A cover crop
keeps the whole --focus box (source pixels, x0,y0,x1,y1) in frame and stops with exit 1 when it cannot.
Each --safe box (a logo, text, a face; source pixels) must end at least --margin of the output's short
side inside every edge, or the export stops with exit 1. Box coordinates are in the image as viewers show
it, after any EXIF rotation.

Privacy: the output is written from decoded pixels only, so it carries no EXIF, XMP, IPTC, comments, PNG
text chunks, or embedded thumbnails. A color profile is converted to sRGB and then dropped (untagged
images are shown as sRGB). The script lists the metadata names the source had, never their values, and
re-reads the output to confirm none is left. It does not alter pixels for any other purpose.

Exit codes: 0 written, 1 a stop condition (focus does not fit, safe box too close to an edge, metadata
left in the output), 2 bad input or an upscale above 4x. Requires Pillow only.
"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

PRESETS = {
    "x-landscape": (1600, 900),
    "x-square": (1080, 1080),
    "x-portrait": (1080, 1350),
    "nft-portrait": (1024, 1536),
}
X_MAX_BYTES = 5 * 1024 * 1024  # X image limit: https://help.x.com/en/business-and-advertising/creative-ad-specifications
MAX_UPSCALE = 4.0
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_PIXEL_CHUNKS = {"IHDR", "PLTE", "tRNS", "IDAT", "IEND"}
PNG_TEXT_CHUNKS = {"tEXt", "zTXt", "iTXt"}
# Keywords from the PNG spec (plus XMP); any other keyword is free text that could itself hold personal data.
PNG_STANDARD_KEYWORDS = {"Title", "Author", "Description", "Copyright", "Creation Time", "Software", "Disclaimer",
                         "Warning", "Source", "Comment", "XML:com.adobe.xmp"}
JPEG_APP_LABELS = {
    b"Exif": "EXIF",
    b"http://ns.adobe.com/xap/1.0/": "XMP",
    b"http://ns.adobe.com/xmp/extension/": "XMP extension",
    b"Photoshop 3.0": "IPTC/Photoshop",
    b"ICC_PROFILE": "ICC profile",
    b"JFXX": "JFIF thumbnail",
    b"MPF": "MPF embedded images",
    b"Adobe": "Adobe",
}


def size_arg(text):
    match = re.fullmatch(r"(\d+)x(\d+)", text.strip().lower())
    if not match or not all(1 <= int(v) <= 16384 for v in match.groups()):
        raise argparse.ArgumentTypeError("use WxH with each side 1..16384, for example 1600x900")
    return int(match.group(1)), int(match.group(2))


def box_arg(text):
    try:
        values = [float(v) for v in text.split(",")]
    except ValueError:
        values = []
    if len(values) != 4 or values[2] <= values[0] or values[3] <= values[1] or min(values) < 0:
        raise argparse.ArgumentTypeError("use x0,y0,x1,y1 in source pixels with x1 > x0 and y1 > y0")
    return values


def margin_arg(text):
    try:
        value = float(text)
    except ValueError:
        value = -1.0
    if not 0 <= value < 0.5:
        raise argparse.ArgumentTypeError("use a fraction of the short side from 0 to below 0.5, for example 0.04")
    return value


def quality_arg(text):
    if not text.isdigit() or not 1 <= int(text) <= 100:
        raise argparse.ArgumentTypeError("use a whole number from 1 to 100")
    return int(text)


def color_arg(text):
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        raise argparse.ArgumentTypeError("use #RRGGBB, for example #000000")
    return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))


def png_metadata(data):
    """Names of non-pixel PNG chunks; text chunks show a standard keyword only, never a value."""
    names, pos = [], len(PNG_SIGNATURE)
    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8].decode("latin-1")
        if kind not in PNG_PIXEL_CHUNKS:
            name = kind
            if kind in PNG_TEXT_CHUNKS:
                keyword = data[pos + 8:pos + 8 + min(length, 80)].split(b"\0")[0].decode("latin-1")
                name = f"{kind}:{keyword if keyword in PNG_STANDARD_KEYWORDS else '<non-standard keyword>'}"
            names.append(name)
        if kind == "IEND":
            break
        pos += 12 + length
    return names


def jpeg_metadata(data):
    """Names of JPEG segments other than the image data and the plain JFIF header."""
    names, pos = [], 2
    while pos + 4 <= len(data) and data[pos] == 0xFF:
        marker = data[pos + 1]
        if marker == 0xFF:
            pos += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            pos += 2
            continue
        if marker in (0xD9, 0xDA):  # end of image, start of scan: no metadata segments follow in practice
            break
        length = int.from_bytes(data[pos + 2:pos + 4], "big")
        payload = data[pos + 4:pos + 2 + length]
        if 0xE0 <= marker <= 0xEF:
            if not (marker == 0xE0 and payload.startswith(b"JFIF\0")):
                # Prefix match: APP14 is "Adobe" followed directly by version bytes, not a NUL.
                label = next((v for k, v in sorted(JPEG_APP_LABELS.items(), key=lambda kv: -len(kv[0]))
                              if payload.startswith(k)), "unknown")
                names.append(f"APP{marker - 0xE0}:{label}")
        elif marker == 0xFE:
            names.append("COM comment")
        pos += 2 + length
    return names


def file_metadata(path, image):
    data = Path(path).read_bytes()
    if data.startswith(PNG_SIGNATURE):
        names = png_metadata(data)
    elif data.startswith(b"\xff\xd8"):
        names = jpeg_metadata(data)
    else:
        names = [f"info:{key}" for key in sorted(image.info) if isinstance(key, str)]
    if image is not None:
        try:
            from PIL import ExifTags

            exif = image.getexif()
            names += [f"EXIF:{ExifTags.TAGS.get(tag, hex(tag))}" for tag in sorted(exif)]
        except Exception:  # noqa: BLE001 - tag names are best effort; still say an EXIF block is there
            if "exif" in image.info:
                names.append("EXIF")
            return names
        try:
            if exif.get_ifd(ExifTags.IFD.IFD1):
                names.append("EXIF thumbnail")
        except Exception:  # noqa: BLE001 - older Pillow has no ExifTags.IFD; the output is rebuilt from pixels anyway
            pass
    return names


def ascii_slug(name):
    """An ASCII, space-free spelling of a file name, or None when the name is already clean."""
    if re.fullmatch(r"[A-Za-z0-9._-]+", name):
        return None
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    text = unicodedata.normalize("NFKD", stem.replace("đ", "d").replace("Đ", "D"))
    text = re.sub(r"[^a-z0-9._-]+", "-", text.encode("ascii", "ignore").decode().lower()).strip("-") or "image"
    return f"{text}.{suffix.lower()}" if suffix else text


def load(path, Image, ImageOps):
    image = Image.open(path)
    frames = getattr(image, "n_frames", 1)
    image = ImageOps.exif_transpose(image)
    if image.mode == "F":
        raise ValueError("a floating-point image has no fixed value scale; save an 8-bit or 16-bit copy")
    if image.mode in ("I", "I;16", "I;16B", "I;16L", "I;16N"):
        image = image.convert("I").point(lambda v: v * (1 / 256)).convert("L")  # plain convert clips at 255
    return image, frames


def to_srgb(image, warnings):
    """RGB or RGBA pixels in sRGB; a source profile is converted, then not carried over."""
    from PIL import Image

    alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
    icc = image.info.get("icc_profile")
    if image.mode == "P":
        image = image.convert("RGBA" if alpha else "RGB")
    mode = "RGBA" if alpha else "RGB"
    if icc:
        try:
            import io

            from PIL import ImageCms

            source = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            base = image.convert("RGBA" if image.mode in ("LA", "PA") else image.mode)
            if base.mode not in ("RGB", "RGBA", "L", "CMYK"):
                base = base.convert(mode)
            out_mode = "RGBA" if base.mode == "RGBA" else "RGB"
            converted = ImageCms.profileToProfile(base, source, ImageCms.createProfile("sRGB"), outputMode=out_mode)
            image = converted if converted is not None else base
        except Exception as error:  # noqa: BLE001 - a broken profile must not stop a privacy export
            warnings.append(f"could not convert the color profile to sRGB ({type(error).__name__}); colors may shift")
    image = image.convert(mode)
    # A fresh image from raw pixels carries no info, EXIF, text, or profile from the source.
    return Image.frombytes(image.mode, image.size, image.tobytes())


def plan_cover(src_w, src_h, out_w, out_h, focus):
    """Largest window of the output aspect that holds the focus box, centered on it. None if it cannot."""
    aspect = out_w / out_h
    win_w = min(src_w, src_h * aspect)
    win_h = win_w / aspect
    fx0, fy0, fx1, fy1 = focus
    if fx1 - fx0 > win_w + 1e-6 or fy1 - fy0 > win_h + 1e-6:
        return None
    cx, cy = (fx0 + fx1) / 2, (fy0 + fy1) / 2
    x0 = min(max(cx - win_w / 2, 0.0), src_w - win_w)
    y0 = min(max(cy - win_h / 2, 0.0), src_h - win_h)
    return (x0, y0, x0 + win_w, y0 + win_h), win_w, win_h


def to_output(box, crop, scale, offset):
    return [round((box[0] - crop[0]) * scale + offset[0], 1), round((box[1] - crop[1]) * scale + offset[1], 1),
            round((box[2] - crop[0]) * scale + offset[0], 1), round((box[3] - crop[1]) * scale + offset[1], 1)]


def check_safe(boxes, crop, scale, offset, out_w, out_h, margin):
    need = margin * min(out_w, out_h)
    results = []
    for index, box in enumerate(boxes, 1):
        out = to_output(box, crop, scale, offset)
        gaps = {"left": out[0], "top": out[1], "right": out_w - out[2], "bottom": out_h - out[3]}
        failed = [{"edge": edge, "distance_px": round(gap, 1)} for edge, gap in gaps.items() if gap < need - 0.05]
        results.append({"index": index, "source_box": box, "output_box": out, "required_px": round(need, 1),
                         "distances_px": {k: round(v, 1) for k, v in gaps.items()}, "failed_edges": failed,
                         "ok": not failed})
    return results


def fmt_box(box):
    return ",".join(f"{v:g}" for v in box)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="source", required=True, help="source image")
    parser.add_argument("--out", required=True, help="output .png, .jpg, or .jpeg")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--preset", choices=sorted(PRESETS), help="output size by name")
    target.add_argument("--size", type=size_arg, help="custom output size WxH")
    parser.add_argument("--fit", choices=("cover", "pad"), default="cover",
                        help="cover crops to fill the frame (default); pad letterboxes the whole image")
    parser.add_argument("--focus", type=box_arg, help="x0,y0,x1,y1 source box a cover crop must keep (default: centered)")
    parser.add_argument("--safe", type=box_arg, action="append", default=[],
                        help="x0,y0,x1,y1 source box that must stay inside the margin; repeat for each")
    parser.add_argument("--margin", type=margin_arg, default=0.04, help="safe margin as a fraction of the short side")
    parser.add_argument("--format", choices=("png", "jpeg"), help="output format (default: from --out extension)")
    parser.add_argument("--quality", type=quality_arg, default=92, help="JPEG quality 1..100 (default 92)")
    parser.add_argument("--pad-color", type=color_arg, default=(0, 0, 0),
                        help="#RRGGBB for pad bars and for flattening transparency into JPEG (default #000000)")
    parser.add_argument("--report", help="write a JSON report here")
    args = parser.parse_args()

    source_path, out_path = Path(args.source), Path(args.out)
    suffix = out_path.suffix.lower()
    implied = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg"}.get(suffix)
    fmt = args.format or implied
    if implied is None:
        parser.error(f"--out must end in .png, .jpg, or .jpeg (got {suffix or 'no extension'})")
    if implied != fmt:
        parser.error(f"--out extension {suffix} does not match --format {fmt}")
    if args.focus and args.fit == "pad":
        parser.error("--focus only applies to --fit cover; pad keeps the whole image")
    for flag, value in (("--out", args.out), ("--report", args.report)):
        if value and not Path(value).resolve().parent.is_dir():
            parser.error(f"{flag} folder does not exist: {Path(value).parent}")
    if not source_path.is_file():
        parser.error(f"input not found: {source_path}")
    if out_path.exists() and out_path.resolve() == source_path.resolve():
        parser.error("--out must not overwrite the source image")
    if args.report and Path(args.report).resolve() in (source_path.resolve(), out_path.resolve()):
        parser.error("--report must be a separate file")
    try:
        from PIL import Image, ImageOps
    except ImportError:
        parser.error("Pillow is required: uv run --with pillow ... (or python3 -m pip install pillow)")

    warnings = []
    try:
        image, frames = load(source_path, Image, ImageOps)
        with Image.open(source_path) as opened:
            removed = file_metadata(source_path, opened)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        parser.error(f"cannot read {source_path}: {type(error).__name__}: {error}")
    if frames > 1:
        warnings.append(f"source has {frames} frames; only the first is exported")
    src_w, src_h = image.size
    out_w, out_h = PRESETS[args.preset] if args.preset else args.size
    for name, box in [("--focus", args.focus)] + [("--safe", b) for b in args.safe]:
        if box is not None and (box[2] > src_w or box[3] > src_h):
            parser.error(f"{name} {fmt_box(box)} is outside the {src_w}x{src_h} source")

    report = {"ok": False, "input": {"path": str(source_path), "width": src_w, "height": src_h},
              "output": {"path": str(out_path), "width": out_w, "height": out_h, "format": fmt},
              "preset": args.preset or "custom", "fit": args.fit, "margin": args.margin,
              "removed_metadata": removed, "warnings": warnings, "stop": []}

    def finish(code):
        report["ok"] = code == 0
        for line in warnings:
            print(f"warning: {line}")
        for line in report["stop"]:
            print(f"stop: {line}", file=sys.stderr)
        if args.report:
            try:
                Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            except OSError as error:
                print(f"error: cannot write --report {args.report}: {type(error).__name__}: {error}", file=sys.stderr)
                return 2
        return code

    if args.fit == "cover":
        focus = args.focus or [src_w / 2, src_h / 2, src_w / 2, src_h / 2]
        plan = plan_cover(src_w, src_h, out_w, out_h, focus)
        if plan is None:
            aspect = out_w / out_h
            win_w = min(src_w, src_h * aspect)
            report["stop"].append(f"--focus {fmt_box(focus)} does not fit a {out_w}x{out_h} cover crop of this image "
                                  f"(largest window {win_w:.0f}x{win_w / aspect:.0f} source px); "
                                  "use --fit pad, a smaller --focus, or another preset")
            return finish(1)
        crop, win_w, _ = plan
        scale, offset, placed = out_w / win_w, (0, 0), (out_w, out_h)
        report["focus"] = {"source_box": focus, "output_box": to_output(focus, crop, scale, offset)}
    else:
        crop = (0.0, 0.0, float(src_w), float(src_h))
        scale = min(out_w / src_w, out_h / src_h)
        placed = (max(1, round(src_w * scale)), max(1, round(src_h * scale)))
        offset = ((out_w - placed[0]) // 2, (out_h - placed[1]) // 2)
    report.update(crop_box=[round(v, 2) for v in crop], scale=round(scale, 4), pad_offset=list(offset))
    if scale > MAX_UPSCALE:
        print(f"error: this export needs a {scale:.2f}x upscale (limit {MAX_UPSCALE:g}x); "
              "upscale the source first with the image-enhance steps, then export", file=sys.stderr)
        return 2
    if scale > 1:
        warnings.append(f"upscaling {scale:.2f}x with Lanczos; above 2x, upscale with an AI upscaler first")

    report["safe_boxes"] = check_safe(args.safe, crop, scale, offset, out_w, out_h, args.margin)
    for result in report["safe_boxes"]:
        for edge in result["failed_edges"]:
            report["stop"].append(f"--safe box {result['index']} ({fmt_box(result['source_box'])} source px, "
                                  f"{fmt_box(result['output_box'])} output px) is {edge['distance_px']:g} px from the "
                                  f"{edge['edge']} edge; needs {result['required_px']:g} px")
    if report["stop"]:
        return finish(1)

    pixels = to_srgb(image, warnings)
    resized = pixels.resize(placed, Image.LANCZOS, box=crop)
    if args.fit == "pad":
        canvas = Image.new(pixels.mode, (out_w, out_h), args.pad_color + ((255,) if pixels.mode == "RGBA" else ()))
        canvas.paste(resized, offset)
        resized = canvas
    if fmt == "jpeg" and resized.mode == "RGBA":
        flat = Image.new("RGB", resized.size, args.pad_color)
        flat.paste(resized, mask=resized.getchannel("A"))
        resized = flat
        warnings.append("transparency flattened onto --pad-color for JPEG")
    try:
        if fmt == "jpeg":
            resized.save(out_path, "JPEG", quality=args.quality, optimize=True)
        else:
            resized.save(out_path, "PNG", optimize=True)
        with Image.open(out_path) as check:
            left, written = file_metadata(out_path, check), check.size
    except (OSError, ValueError) as error:
        parser.error(f"cannot write {out_path}: {type(error).__name__}: {error}")
    report["output"]["bytes"] = out_path.stat().st_size
    report["remaining_metadata"] = left
    if left or written != (out_w, out_h):
        out_path.unlink()
        report["stop"].append(f"output check failed (metadata left: {', '.join(left) or 'none'}; size {written}); "
                              "output removed")
        return finish(1)
    if args.preset and args.preset.startswith("x-") and report["output"]["bytes"] > X_MAX_BYTES:
        warnings.append("output is over X's 5 MB image limit; use --format jpeg or a lower --quality")
    slug = ascii_slug(out_path.name)
    if slug:
        warnings.append(f"file name has spaces or non-ASCII characters; consider renaming to {slug}")
        report["suggested_name"] = slug

    print(f"wrote {out_path} {out_w}x{out_h} {fmt} ({report['preset']}, {args.fit}, scale {scale:.3f})")
    print(f"crop box (source px): {fmt_box(report['crop_box'])}")
    if args.focus:
        print(f"focus (output px): {fmt_box(report['focus']['output_box'])}")
    for result in report["safe_boxes"]:
        print(f"safe box {result['index']} (output px): {fmt_box(result['output_box'])} ok, "
              f"min gap {min(result['distances_px'].values()):g} px >= {result['required_px']:g} px")
    print(f"metadata removed: {', '.join(removed) if removed else 'none found'}; output re-read: none left")
    return finish(0)


if __name__ == "__main__":
    sys.exit(main())
