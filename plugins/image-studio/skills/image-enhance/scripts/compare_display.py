#!/usr/bin/env python3
"""Show and measure whether an enhanced image is visibly better than its source at display size.

Writes before-after.png (source left, candidate right, both resized to --width with Lanczos),
optional 100% crops, and metrics.json, then prints the verdict. Metrics are a screen, not proof:
a person still looks at before-after.png. Requires Pillow only.

Transparent images are shown on a dark backdrop in before-after.png and a light one in
before-after-light.png, and their cutout edges are compared: edges much noisier than the source fail,
and so does a changed cutout shape or a candidate whose body is see-through (alpha below 255,
as image generators often write). Edges at least 20% cleaner, or a see-through body made solid,
count as a visible improvement; a body made solid has its color and fidelity checks measured with
the source's opacity, since a solid body is meant to look brighter or darker on the backdrop.
Edge noise is measured relative to the noise inside the object, so a detailed object or a sharper
upscale does not count as a noisy edge, while a halo or speckled rim does. It is measured at the
display width, or at the source width when the display is wider.
"""

import argparse
import json
import math
import sys
from pathlib import Path

# ponytail: thresholds calibrated on anime/2D art (references/recipes.md); recheck for photos.
LIMITS = {"min_display_difference": 1.0, "min_sharpness_gain": 1.15, "max_color_shift": 3.0, "min_fidelity_psnr": 25.0,
          "max_edge_ratio_for_gain": 0.8, "min_sharpness_for_edge_gain": 0.9, "max_edge_ratio": 1.35,
          "min_alpha_iou": 0.97, "min_body_alpha": 254.0}
DARK, LIGHT = (30, 30, 30), (235, 235, 235)


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
    gain, guard = [], []  # gain: the visible improvement is missing; guard: something got worse
    if metrics["display_difference"] < LIMITS["min_display_difference"]:
        gain.append("invisible at display size: candidate is almost identical to the resized source")
    if metrics["sharpness_gain"] < LIMITS["min_sharpness_gain"]:
        gain.append("not measurably sharper at display size")
    if metrics["color_shift"] > LIMITS["max_color_shift"]:
        guard.append("average color or brightness shifted; that is a grade, not an enhancement")
    if metrics["fidelity_psnr"] < LIMITS["min_fidelity_psnr"]:
        guard.append("candidate no longer matches the source when reduced back to source size (invented or moved content)")
    return before, after, metrics, gain, guard


def flatten(image, color):
    from PIL import Image

    if image.mode != "RGBA":
        return image
    flat = Image.new("RGB", image.size, color)
    flat.paste(image, mask=image.getchannel("A"))
    return flat


def cutout_mask(image, size=None):
    """The object's shape: alpha at least half the image's highest alpha, so a faint object still has a shape."""
    from PIL import Image

    alpha = image.getchannel("A")
    if size:
        alpha = alpha.resize(size, Image.LANCZOS)
    cut = max(1, (alpha.getextrema()[1] + 1) // 2)
    return alpha.point(lambda v: 255 if v >= cut else 0)


def edge_noise(image, width, color):
    """Local noise along the cutout edge over the noise inside the object, at display size.

    Halos, specks and stair-steps raise the edge alone; sharper detail raises both, so the ratio holds.
    """
    from PIL import ImageChops, ImageFilter, ImageStat

    shown = to_width(image, width)
    mask = cutout_mask(shown)
    band = ImageChops.difference(mask.filter(ImageFilter.MaxFilter(3)), mask.filter(ImageFilter.MinFilter(3)))
    if not band.getbbox():
        return 0.0
    gray = flatten(shown, color).convert("L")
    noise = ImageChops.difference(gray, gray.filter(ImageFilter.MedianFilter(3)))
    inside = mask.filter(ImageFilter.MinFilter(7))
    interior = ImageStat.Stat(noise, mask=inside).mean[0] if inside.getbbox() else 0.0
    return ImageStat.Stat(noise, mask=band).mean[0] / max(interior, 0.5)  # 0.5: a flat interior has ~no noise


def body_alpha(image):
    """Mean alpha inside the cutout, away from its edge: 255 for a solid object."""
    from PIL import ImageFilter, ImageStat

    body = cutout_mask(image).filter(ImageFilter.MinFilter(9))
    return ImageStat.Stat(image.getchannel("A"), mask=body).mean[0] if body.getbbox() else 255.0


def check_edges(source, candidate, width, metrics, gain, guard):
    """Transparent images: edges not much noisier than the source at display size, and the same cutout shape."""
    from PIL import Image, ImageChops

    metrics.update(body_alpha_source=round(body_alpha(source), 2), body_alpha=round(body_alpha(candidate), 2))
    solidified = metrics["body_alpha_source"] < LIMITS["min_body_alpha"] <= metrics["body_alpha"]
    baseline = source
    if solidified:
        # A solid body looks brighter or darker on the backdrop; that is the fix, not a grade or invented content.
        # Judge the colors with the source's opacity, and the edges against the source with its body made solid.
        same = candidate.copy()
        same.putalpha(source.getchannel("A").resize(candidate.size, Image.LANCZOS))
        _, _, colors, _, guard = measure(flatten(source, DARK), flatten(same, DARK), width)
        metrics.update(color_shift=colors["color_shift"], fidelity_psnr=colors["fidelity_psnr"])
        scale = 255 / max(metrics["body_alpha_source"], 1)
        baseline = source.copy()
        baseline.putalpha(source.getchannel("A").point(lambda v: min(255, round(v * scale))))
    # Beyond the source's own width its edges are interpolated, smooth by construction, so an upscale is judged there.
    edge_width = min(width, source.width)
    source_edges = max(edge_noise(baseline, edge_width, color) for color in (DARK, LIGHT))
    candidate_edges = max(edge_noise(candidate, edge_width, color) for color in (DARK, LIGHT))
    first, second = cutout_mask(source), cutout_mask(candidate, source.size)
    union = ImageChops.lighter(first, second).histogram()[255]
    iou = ImageChops.darker(first, second).histogram()[255] / union if union else 1.0
    ratio = candidate_edges / source_edges if source_edges else (1.0 if not candidate_edges else math.inf)
    metrics.update(edge_width=edge_width, edge_noise_source=round(source_edges, 2),
                   edge_noise_candidate=round(candidate_edges, 2), edge_ratio=round(ratio, 3) if math.isfinite(ratio) else None, alpha_iou=round(iou, 4))
    cleaner = ratio <= LIMITS["max_edge_ratio_for_gain"] and metrics["sharpness_gain"] >= LIMITS["min_sharpness_for_edge_gain"]
    if cleaner or solidified:
        gain = []  # cleaner edges, or a see-through body made solid, are themselves the visible improvement
    if candidate_edges > source_edges * LIMITS["max_edge_ratio"] + 0.1:  # 0.1: ignore noise in tiny values
        guard.append("cutout edges are noisier than the source at display size (jagged, speckled or haloed)")
    if iou < LIMITS["min_alpha_iou"]:
        guard.append("cutout shape changed: the transparent area moved, grew or shrank")
    if metrics["body_alpha"] < LIMITS["min_body_alpha"]:
        guard.append("the cutout body is see-through (alpha below 255); make it solid unless the object is meant to be transparent")
    return gain, guard


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
    # Start inside the candidate and keep at least 1 pixel: a candidate smaller than the source can round
    # a small box to nothing or push it past the edge, where Pillow would pad with black.
    left_x, top = min(round(x * scale), candidate.width - 1), min(round(y * scale), candidate.height - 1)
    right = candidate.crop((left_x, top, max(round((x + w) * scale), left_x + 1), max(round((y + h) * scale), top + 1)))
    left = source.crop((x, y, x + w, y + h)).resize(right.size, Image.LANCZOS)
    return side_by_side(left, right)


def box_arg(text):
    values = [int(v) for v in text.split(",")]
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0 or min(values) < 0:
        raise argparse.ArgumentTypeError("use x,y,width,height in source pixels")
    return values


def load_image(path, Image, ImageOps):
    """RGB, or RGBA when the image has transparent pixels."""
    image = ImageOps.exif_transpose(Image.open(path))
    if image.mode in ("I", "I;16", "I;16B", "I;16L", "I;16N"):
        image = image.convert("I").point(lambda v: v * (1 / 256))  # 16-bit gray to 8-bit; plain convert clips at 255
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        if rgba.getchannel("A").getextrema()[0] < 255:
            return rgba
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
        source, candidate = (load_image(p, Image, ImageOps) for p in (args.source, args.candidate))
        cutout = "RGBA" in (source.mode, candidate.mode)
        if cutout:
            source, candidate = source.convert("RGBA"), candidate.convert("RGBA")
        if abs(source.width / source.height - candidate.width / candidate.height) > 0.01:
            raise ValueError("source and candidate aspect ratios differ; compare the same framing")
        for x, y, w, h in args.crop:
            if x + w > source.width or y + h > source.height:
                raise ValueError(f"crop {x},{y},{w},{h} falls outside the source")
        shown = (flatten(source, DARK), flatten(candidate, DARK))
        before, after, metrics, gain, guard = measure(*shown, args.width)
        if cutout:
            gain, guard = check_edges(source, candidate, args.width, metrics, gain, guard)
            light = measure(flatten(source, LIGHT), flatten(candidate, LIGHT), args.width)
        failures = gain + guard
        result = {"visible_improvement": not failures, "failures": failures, "metrics": metrics, "limits": LIMITS}
        crops = [crop_pair(*shown, box) for box in args.crop]  # fail before creating the folder
        args.out.mkdir(parents=True)
        side_by_side(before, after).save(args.out / "before-after.png")
        if cutout:
            side_by_side(light[0], light[1]).save(args.out / "before-after-light.png")
        for number, crop in enumerate(crops, 1):
            crop.save(args.out / f"crop-{number}.png")
        (args.out / "metrics.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        parser.error(f"{type(error).__name__}: {error}")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
