#!/usr/bin/env python3
"""Score a defect hunt against a hand-labelled answer key.

  python3 bench/score.py --truth bench/cases/NAME/truth.json --found found.md [--json]

truth.json: {"image": "image.png", "size": [W, H],
             "defects": [{"id": "D1", "box": [x0, y0, x1, y1], "kind": "hand", "note": "six fingers"}]}
found: the image-hunter reply (a markdown table whose second column is "x0,y0,x1,y1"),
or a JSON list of {"box": [x0, y0, x1, y1]}.

A found box hits a true defect when the boxes overlap by IoU >= 0.1 or the found box's
center lies inside the true box (hunters often box tighter or looser than the label).
Matching is one to one, best overlap first; a duplicate box scores as a miss. Rows without a
box ("whole image") and boxes covering a quarter of the image or more never match. Recall = true defects found / all true defects;
precision = found boxes that hit something / all found boxes.

Exit codes: 0 scored, 2 bad input.
"""
import argparse
import json
import re
import sys
from pathlib import Path

BOX = re.compile(r"^\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*$")


class BenchError(Exception):
    pass


def check_box(box, where):
    if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, int) for v in box)):
        raise BenchError(f"{where}: box must be four integers [x0, y0, x1, y1].")
    if box[2] <= box[0] or box[3] <= box[1]:
        raise BenchError(f"{where}: box {box} has no area.")
    return box


def load_truth(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BenchError(f"Cannot read truth file: {exc}")
    defects = data.get("defects") if isinstance(data, dict) else None
    if not isinstance(defects, list) or not defects:
        raise BenchError("truth.json needs a non-empty \"defects\" list.")
    ids = set()
    for n, d in enumerate(defects):
        if not isinstance(d, dict) or not isinstance(d.get("id"), str) or not isinstance(d.get("kind"), str):
            raise BenchError(f"defect {n}: needs string \"id\" and \"kind\".")
        if d["id"] in ids:
            raise BenchError(f"defect {d['id']}: duplicate id.")
        ids.add(d["id"])
        check_box(d.get("box"), d["id"])
    return defects


def load_found(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise BenchError(f"Cannot read found file: {exc}")
    if text.lstrip().startswith("["):
        try:
            items = json.loads(text)
        except ValueError as exc:
            raise BenchError(f"Found file is not valid JSON: {exc}")
        return [check_box(i.get("box") if isinstance(i, dict) else None, f"found {n}") for n, i in enumerate(items)]
    boxes = []
    for line in text.splitlines():
        cells = [c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2:
            m = BOX.match(cells[1])
            if m:
                boxes.append(check_box([int(v) for v in m.groups()], f"table row {cells[0]}"))
            elif cells[0].isdigit():
                # A numbered row without a box ("whole image") cannot point at a labelled defect.
                boxes.append(None)
    return boxes


def iou(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def hits(found, true):
    cx, cy = (found[0] + found[2]) / 2, (found[1] + found[3]) / 2
    return iou(found, true) >= 0.1 or (true[0] <= cx <= true[2] and true[1] <= cy <= true[3])


def score(truth, found, size=None):
    """One-to-one matching: each found box claims at most one defect, best overlap first.

    A box covering a quarter of the image or more is a whole-image note, not a located defect,
    so it never matches (the hunter's own rule); neither does a row without a box.
    """
    limit = size[0] * size[1] / 4 if size else None
    located = [b if b is not None and not (limit and (b[2] - b[0]) * (b[3] - b[1]) >= limit) else None for b in found]
    pairs = sorted(((iou(b, d["box"]), n, d["id"]) for n, b in enumerate(located) if b is not None
                    for d in truth if hits(b, d["box"])), reverse=True)
    matched, used = {}, set()
    for _, n, did in pairs:
        if n not in used and did not in matched:
            matched[did] = n
            used.add(n)
    kinds = {}
    for d in truth:
        k = kinds.setdefault(d["kind"], [0, 0])
        k[1] += 1
        k[0] += d["id"] in matched
    return {"true_defects": len(truth), "found_boxes": len(found), "found_true": len(matched),
            "recall": round(len(matched) / len(truth), 3),
            "precision": round(len(used) / len(found), 3) if found else None,
            "missed": [d["id"] + " (" + d["kind"] + ")" for d in truth if d["id"] not in matched],
            "by_kind": {k: f"{v[0]}/{v[1]}" for k, v in sorted(kinds.items())}}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--truth", required=True)
    p.add_argument("--found", required=True)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    try:
        truth = load_truth(args.truth)
        size = json.loads(Path(args.truth).read_text(encoding="utf-8")).get("size")
        if size is not None and not (isinstance(size, list) and len(size) == 2 and all(isinstance(v, int) and v > 0 for v in size)):
            raise BenchError("truth.json \"size\" must be [width, height].")
        result = score(truth, load_found(args.found), size)
    except BenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result))
    else:
        print(f"Recall {result['recall']:.0%} ({result['found_true']}/{result['true_defects']}), "
              f"precision {'n/a' if result['precision'] is None else format(result['precision'], '.0%')} "
              f"({result['found_boxes']} boxes)")
        print("By kind: " + ", ".join(f"{k} {v}" for k, v in result["by_kind"].items()))
        if result["missed"]:
            print("Missed: " + ", ".join(result["missed"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
