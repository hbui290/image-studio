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

Text boxes (optional, text layers only; without "box" a text layer is one line centered on x, y):
  {"text": "Grand opening this Saturday", "font": "...", "size": 0.12, "box": [0.1, 0.6, 0.9, 0.9],
   "overflow": "shrink", "align": "center"}
  "box" is [x0, y0, x1, y1] as shares of the canvas (x of width, y of height); x, y are then ignored.
  "overflow" (needs "box", default "wrap"):
    "wrap"   break lines at spaces to the box width; if the lines are taller than the box, exit 2
    "shrink" wrap, then binary-search the largest size from 4 px up to "size" that fits; exit 2 if even 4 px does not
    "clip"   wrap at "size" and cut off anything outside the box
  "align" (needs "box", default "left"): left, center, or right inside the box. "\n" forces a line break.

A PNG output carries the resolved layout (final px size, box, and lines of every text layer) in a PNG text chunk (tEXt or iTXt)
named "image-studio-layout". Read it back with:
  python3 -c "import sys; from PIL import Image; print(Image.open(sys.argv[1]).text['image-studio-layout'])" out.png
JPEG and WebP outputs do not carry it.

Exit codes: 0 written, 2 bad input.
"""

# Wrapping and the shrink binary search are adapted from scenario-labs/skills (MIT, Copyright (c) 2026 Scenario Inc.),
# see THIRD_PARTY_NOTICES.md in the plugin folder.

import argparse
import json
import re
import sys
from pathlib import Path

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
MIN_SHRINK_SIZE = 4  # px
LAYOUT_KEY = "image-studio-layout"
OVERFLOWS = ("clip", "wrap", "shrink")
ALIGNS = ("left", "center", "right")


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


def wrap_lines(draw, text, font, max_width):
    """Break text at spaces to max_width; a word wider than the box is split by characters.

    Returns (lines, split) where split says some word had to be broken mid-word."""
    lines, split = [], False
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split():
            trial = f"{current} {word}".strip()
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
                continue
            if current: lines.append(current)
            current = word
            while len(current) > 1 and draw.textlength(current, font=font) > max_width:
                split = True
                head = current
                while len(head) > 1 and draw.textlength(head, font=font) > max_width: head = head[:-1]
                lines.append(head)
                current = current[len(head):]
        lines.append(current)
    return lines, split


def text_box_layout(layer, name, draw, ImageFont, font_path, size, stroke, W, H):
    """Return (font, size, lines, line_height, pixel_box) for a text layer with a box."""
    box = layer["box"]
    if (not isinstance(box, list) or len(box) != 4
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 for v in box)
            or box[0] >= box[2] or box[1] >= box[3]):
        raise LayoutError(f"text {name}: box must be [x0, y0, x1, y1] as shares from 0 to 1 with x0 < x1 and y0 < y1")
    px = (round(box[0] * W), round(box[1] * H), round(box[2] * W), round(box[3] * H))
    inner_w, inner_h = px[2] - px[0] - 2 * stroke, px[3] - px[1] - 2 * stroke  # the outline stays inside the box

    def lay(px_size):
        font = ImageFont.truetype(font_path, px_size)
        lines, split = wrap_lines(draw, layer["text"], font, inner_w)
        line_height = round(px_size * 1.2)
        return font, lines, line_height, line_height * len(lines), split

    def fits(px_size):
        try:
            if inner_w <= 0: return False
            _, _, _, total, split = lay(px_size)
            return total <= inner_h and not split  # shrinking must not break a word
        except OSError: return False  # some fonts cannot be measured at tiny sizes

    overflow = layer.get("overflow", "wrap")
    try:
        ImageFont.truetype(font_path, size)  # a broken font is a font error, not "does not fit"
        if overflow == "shrink":
            lo, hi = min(MIN_SHRINK_SIZE, size), size
            if not fits(lo):
                raise LayoutError(f"text {name}: does not fit the box ({px[2] - px[0]}x{px[3] - px[1]} px) even at {lo} px without breaking a word; enlarge the box or shorten the text")
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if fits(mid): lo = mid
                else: hi = mid - 1
            size = lo
        font, lines, line_height, total, _ = lay(size)
    except OSError as exc:
        raise LayoutError(f"cannot load font {font_path}: {exc}") from None
    if overflow == "wrap" and (inner_w <= 0 or total > inner_h):
        raise LayoutError(f"text {name}: wrapped text is {total} px tall but the box is {px[3] - px[1]} px; "
                          'use "overflow": "shrink" or "clip", or enlarge the box')
    return font, size, lines, line_height, px


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
    resolved = []
    for layer in layout.get("layers", []):
        if not isinstance(layer, dict) or ("image" in layer) == ("text" in layer):
            raise LayoutError('each layer needs exactly one of "image" or "text"')
        boxed = "text" in layer and "box" in layer  # a text box replaces x, y
        cx, cy = (0.0, 0.0) if boxed else (number(layer, "x") * W, number(layer, "y") * H)
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
            if not isinstance(text, str) or not text.strip(): raise LayoutError("text must be a non-empty string")
            font_path = layer.get("font")
            if not isinstance(font_path, str) or not Path(font_path).is_file():
                raise LayoutError(f"text {text!r}: font file not found: {font_path!r} (give a .ttf or .otf path)")
            size = max(1, round(number(layer, "size", 0.001, 1.0) * H))
            name = repr(text)
            for key in ("overflow", "align"):
                if key in layer and "box" not in layer:
                    raise LayoutError(f'text {name}: "{key}" needs a "box"')
            overflow, align = layer.get("overflow", "wrap"), layer.get("align", "left")
            if overflow not in OVERFLOWS: raise LayoutError(f'text {name}: overflow must be one of {", ".join(OVERFLOWS)}, got {overflow!r}')
            if align not in ALIGNS: raise LayoutError(f'text {name}: align must be one of {", ".join(ALIGNS)}, got {align!r}')
            stroke = round(number(layer, "stroke", 0.0, 0.2, 0.0) * H)
            fill, stroke_fill = color(layer, "color", "#FFFFFF"), color(layer, "stroke_color", "#000000")
            draw = ImageDraw.Draw(canvas)
            if "box" in layer:
                font, size, lines, line_height, px = text_box_layout(layer, name, draw, ImageFont, font_path, size, stroke, W, H)
                sheet = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                sd = ImageDraw.Draw(sheet)
                y = px[1] + stroke
                for line in lines:
                    width = sd.textlength(line, font=font)
                    inner = px[2] - px[0] - 2 * stroke
                    x = px[0] + stroke + {"left": 0, "center": (inner - width) / 2, "right": inner - width}[align]
                    sd.text((x, y), line, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill, anchor="la")
                    y += line_height
                if overflow == "clip":  # wrap at "size", then cut off whatever leaves the box
                    mask = Image.new("L", canvas.size, 0)
                    mask.paste(255, px)
                    sheet.putalpha(Image.composite(sheet.getchannel("A"), Image.new("L", canvas.size, 0), mask))
                canvas = Image.alpha_composite(canvas, sheet)
                box = px
                resolved.append({"text": layer["text"], "size_px": size, "box_px": list(px), "lines": lines})
            else:
                try: font = ImageFont.truetype(font_path, size)
                except OSError as exc: raise LayoutError(f"cannot load font {font_path}: {exc}") from None
                draw.text((cx, cy), text, font=font, anchor="mm", fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
                box = tuple(round(v) for v in draw.textbbox((cx, cy), text, font=font, anchor="mm", stroke_width=stroke))
                resolved.append({"text": layer["text"], "size_px": size, "box_px": list(box), "lines": [text]})
        boxes.append((name, box))
    info = dict(layout)
    texts = iter(resolved)
    info["layers"] = [dict(l, resolved=next(texts)) if "text" in l else l for l in layout.get("layers", [])]
    return canvas, boxes, json.dumps({"canvas": [W, H], "layout": info}, ensure_ascii=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("layout", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.out.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        print("error: --out must end in .png, .jpg, .jpeg, or .webp", file=sys.stderr); return 2
    try:
        canvas, boxes, info = compose(args.layout)
        fmt = "JPEG" if args.out.suffix.lower() in (".jpg", ".jpeg") else None
        if args.out.suffix.lower() == ".png":
            from PIL.PngImagePlugin import PngInfo
            meta = PngInfo()
            meta.add_text(LAYOUT_KEY, info)
            canvas.save(args.out, pnginfo=meta)
        else:
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
