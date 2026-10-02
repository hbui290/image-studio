#!/usr/bin/env python3
"""Show and measure whether an enhanced image is visibly better than its source at display size.

Writes before-after.png (source left, candidate right, both resized to --width with Lanczos),
optional 100% crops, and metrics.json, then prints the verdict. Metrics are a screen, not proof:
a person still looks at before-after.png. Requires Pillow only.
"""

import argparse
import json
import math
import sys
from pathlib import Path

# ponytail: thresholds calibrated on anime/2D art (references/recipes.md); recheck for photos.
LIMITS = {"min_display_difference": 1.0, "min_sharpness_gain": 1.15, "max_color_shift": 3.0, "min_fidelity_psnr": 25.0}


def to_width(image, width):
    from PIL import Image

    return image.resize((width, max(1, round(image.height * width / image.width))), Image.LANCZOS)


def sharpness(image):
    from PIL import ImageFilter, ImageStat

    return ImageStat.Stat(image.convert("L").filter(ImageFilter.FIND_EDGES)).mean[0]


def mean_difference(first, second):
    from PIL import ImageChops, ImageStat

    return sum(ImageStat.Stat(ImageChops.difference(first, second)).mean) / 3


def psnr(first, second):
    from PIL import ImageChops, ImageStat

    mse = sum(ImageStat.Stat(ImageChops.difference(first, second)).sum2) / (3 * first.width * first.height)
    return 99.0 if mse == 0 else 10 * math.log10(255 ** 2 / mse)


def measure(source, candidate, width):
    from PIL import Image, ImageStat

    # The baseline takes the same resize path as the candidate, so only the enhancement itself is measured.
    plain = source.resize(candidate.size, Image.LANCZOS)
    before, after = to_width(plain, width), to_width(candidate, width)
    back = candidate.resize(source.size, Image.LANCZOS)
    shift = max(abs(a - b) for a, b in zip(ImageStat.Stat(before).mean, ImageStat.Stat(after).mean))
    metrics = {"display_width": width,
               "display_difference": round(mean_difference(before, after), 3),
               "sharpness_gain": round(sharpness(after) / max(sharpness(before), 1e-9), 3),
               "color_shift": round(shift, 3),
               "fidelity_psnr": round(psnr(source, back), 2)}
    failures = []
    if metrics["display_difference"] < LIMITS["min_display_difference"]:
        failures.append("invisible at display size: candidate is almost identical to the resized source")
    if metrics["sharpness_gain"] < LIMITS["min_sharpness_gain"]:
        failures.append("not measurably sharper at display size")
    if metrics["color_shift"] > LIMITS["max_color_shift"]:
        failures.append("average color or brightness shifted; that is a grade, not an enhancement")
    if metrics["fidelity_psnr"] < LIMITS["min_fidelity_psnr"]:
        failures.append("candidate no longer matches the source when reduced back to source size (invented or moved content)")
    return before, after, metrics, failures


def side_by_side(left, right):
    from PIL import Image

    sheet = Image.new("RGB", (left.width + right.width + 8, max(left.height, right.height)), "white")
    sheet.paste(left, (0, 0))
    sheet.paste(right, (left.width + 8, 0))
    return sheet


def crop_pair(source, candidate, box):
    """Source-pixel box; both sides shown at the candidate's scale so detail is compared 1:1."""
    from PIL import Image

    x, y, w, h = box
    scale = candidate.width / source.width
    left_x, top = round(x * scale), round(y * scale)
    # At least 1 pixel: a candidate smaller than the source can round a small box to nothing.
    right = candidate.crop((left_x, top, max(round((x + w) * scale), left_x + 1), max(round((y + h) * scale), top + 1)))
    left = source.crop((x, y, x + w, y + h)).resize(right.size, Image.LANCZOS)
    return side_by_side(left, right)


def box_arg(text):
    values = [int(v) for v in text.split(",")]
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0 or min(values) < 0:
        raise argparse.ArgumentTypeError("use x,y,width,height in source pixels")
    return values


def load_rgb(path, Image, ImageOps):
    image = ImageOps.exif_transpose(Image.open(path))
    if image.mode in ("I", "I;16", "I;16B", "I;16L", "I;16N"):
        image = image.convert("I").point(lambda v: v / 256)  # 16-bit gray to 8-bit; plain convert clips at 255
    return image.convert("RGB")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--width", type=int, default=1920, help="Display width in CSS pixels x device pixel ratio (1-16384)")
    parser.add_argument("--crop", type=box_arg, action="append", default=[], help="x,y,width,height in source pixels")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output folder already exists")
    if not 0 < args.width <= 16384:
        parser.error("--width must be between 1 and 16384")
    try:
        from PIL import Image, ImageOps
    except ImportError:
        parser.error("Pillow is required: python3 -m pip install pillow")
    try:
        source, candidate = (load_rgb(p, Image, ImageOps) for p in (args.source, args.candidate))
        if abs(source.width / source.height - candidate.width / candidate.height) > 0.01:
            raise ValueError("source and candidate aspect ratios differ; compare the same framing")
        for x, y, w, h in args.crop:
            if x + w > source.width or y + h > source.height:
                raise ValueError(f"crop {x},{y},{w},{h} falls outside the source")
        before, after, metrics, failures = measure(source, candidate, args.width)
        result = {"visible_improvement": not failures, "failures": failures, "metrics": metrics, "limits": LIMITS}
        crops = [crop_pair(source, candidate, box) for box in args.crop]  # fail before creating the folder
        args.out.mkdir(parents=True)
        side_by_side(before, after).save(args.out / "before-after.png")
        for number, crop in enumerate(crops, 1):
            crop.save(args.out / f"crop-{number}.png")
        (args.out / "metrics.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        parser.error(f"{type(error).__name__}: {error}")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
