#!/usr/bin/env python3
"""Compose a finished image from layers: a background, image layers (subject cutout, logo), and text.

Text, numbers, and logos stay out of the generated art and are placed here, so changing a word,
moving the logo, or resizing the subject is an edit to layout.json and one run, not a new generation.

layout.json (paths relative to the file; x, y are the layer's center as a share of the canvas):
  {"background": "art.png",
   "layers": [
     {"image": "boss-cutout.png", "x": 0.72, "y": 0.55, "height": 0.8},
     {"image": "logo.png", "x": 0.3, "y": 0.25, "width": 0.35},
     {"text": "5000+", "font": "/Library/Fonts/Cinzel-Bold.ttf", "size": 0.16, "color": "#F5C542",
      "x": 0.3, "y": 0.5, "stroke": 0.01, "stroke_color": "#1A0E05"}]}
Image layers take "width" (share of canvas width) or "height" (share of canvas height) and keep their
aspect ratio. Text "size" and "stroke" are shares of the canvas height. Layers are drawn in order.

Exit codes: 0 written, 2 bad input.
"""

import argparse
import json
import re
import sys
from pathlib import Path

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class LayoutError(Exception):
    pass


def number(layer, key, low=0.0, high=1.0, default=None):
    value = layer.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not low <= value <= high:
        raise LayoutError(f"layer {layer.get('image') or layer.get('text')!r}: {key} must be a number from {low} to {high}")
    return float(value)


def color(layer, key, default):
    value = layer.get(key, default)
    if not isinstance(value, str) or not HEX.match(value):
        raise LayoutError(f"{key} must look like #RRGGBB, got {value!r}")
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5)) + (255,)


def open_rgba(Image, path):
    if not path.is_file(): raise LayoutError(f"file not found: {path}")
    with Image.open(path) as img:
        return img.convert("RGBA")


def compose(layout_path):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise LayoutError("Pillow is required: uv run --with pillow python3 ... (or pip install pillow)") from None
    try: layout = json.loads(layout_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc: raise LayoutError(f"cannot read {layout_path}: {exc}") from None
    if not isinstance(layout, dict) or not isinstance(layout.get("background"), str) or not isinstance(layout.get("layers", []), list):
        raise LayoutError('layout needs "background" (a file) and "layers" (a list)')
    base = layout_path.parent
    canvas = open_rgba(Image, base / layout["background"])
    W, H = canvas.size
    boxes = []
    for layer in layout.get("layers", []):
        if not isinstance(layer, dict) or ("image" in layer) == ("text" in layer):
            raise LayoutError('each layer needs exactly one of "image" or "text"')
        cx, cy = number(layer, "x") * W, number(layer, "y") * H
        if "image" in layer:
            img = open_rgba(Image, base / str(layer["image"]))
            if "width" in layer: w = number(layer, "width", 0.001, 4.0) * W; h = w * img.size[1] / img.size[0]
            elif "height" in layer: h = number(layer, "height", 0.001, 4.0) * H; w = h * img.size[0] / img.size[1]
            else: w, h = img.size
            img = img.resize((max(1, round(w)), max(1, round(h))), Image.LANCZOS)
            left, top = round(cx - img.size[0] / 2), round(cy - img.size[1] / 2)
            sheet = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            sheet.paste(img, (left, top))  # paste clips a layer that runs past the canvas edge
            canvas = Image.alpha_composite(canvas, sheet)
            box = (max(0, left), max(0, top), min(W, left + img.size[0]), min(H, top + img.size[1]))
            name = str(layer["image"])
        else:
            text = layer["text"]
            if not isinstance(text, str) or not text: raise LayoutError("text must be a non-empty string")
            font_path = layer.get("font")
            if not isinstance(font_path, str) or not Path(font_path).is_file():
                raise LayoutError(f"text {text!r}: font file not found: {font_path!r} (give a .ttf or .otf path)")
            size = max(1, round(number(layer, "size", 0.001, 1.0) * H))
            try: font = ImageFont.truetype(font_path, size)
            except OSError as exc: raise LayoutError(f"cannot load font {font_path}: {exc}") from None
            stroke = round(number(layer, "stroke", 0.0, 0.2, 0.0) * H)
            draw = ImageDraw.Draw(canvas)
            draw.text((cx, cy), text, font=font, anchor="mm", fill=color(layer, "color", "#FFFFFF"),
                      stroke_width=stroke, stroke_fill=color(layer, "stroke_color", "#000000"))
            box = tuple(round(v) for v in draw.textbbox((cx, cy), text, font=font, anchor="mm", stroke_width=stroke))
            name = repr(text)
        boxes.append((name, box))
    return canvas, boxes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("layout", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.out.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        print("error: --out must end in .png, .jpg, .jpeg, or .webp", file=sys.stderr); return 2
    try:
        canvas, boxes = compose(args.layout)
        fmt = "JPEG" if args.out.suffix.lower() in (".jpg", ".jpeg") else None
        (canvas.convert("RGB") if fmt == "JPEG" else canvas).save(args.out, fmt)
    except LayoutError as exc:
        print(f"error: {exc}", file=sys.stderr); return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr); return 2
    print(f"Wrote {args.out} ({canvas.size[0]}x{canvas.size[1]})")
    for name, box in boxes: print(f"- {name}: box {','.join(map(str, box))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
