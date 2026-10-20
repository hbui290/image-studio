#!/usr/bin/env python3
"""Apple Vision on macOS: subject cutout and text reading, with no model download.

  python3 mac_vision.py cutout IN.png OUTDIR [--point X Y]
      Writes OUTDIR/cutout.png (subject on transparency), mask.png, and mask-N.png per detected
      instance; --point keeps only the instance under that pixel.
  python3 mac_vision.py ocr IN.png [--expect TEXT ...]
      Prints every text line with confidence and box [x0, y0, x1, y1]. Each --expect must appear
      (case and spacing ignored), or the run exits 1 and names what is missing or misspelled.
  python3 mac_vision.py hands IN.png
      Prints one box per detected hand and how many of its 21 joints Vision saw. The model is trained on
      photos: use the boxes to crop every hand for review at 100%; a hand it finds is never a pass, and a
      painted hand it misses still needs a look.

Needs macOS 14+ and the Xcode command line tools (swiftc); the Swift helper is built once into
${IMAGE_STUDIO_HOME:-~/.image-studio}/bin (about 2 s). The very first OCR run on a machine can wait
from 30 s to many minutes while macOS prepares its text model; later runs take about 0.3 s. Exit codes: 0 ok, 1 nothing found (no subject, text, or hand) or expected text missing, 2 bad input.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).with_name("mac_vision.swift")


def helper():
    if sys.platform != "darwin":
        raise SystemExit("error: mac_vision.py needs macOS (Apple Vision); elsewhere use rembg for cutouts")
    if int(platform.mac_ver()[0].split(".")[0] or 0) < 14:
        raise SystemExit("error: mac_vision.py needs macOS 14 or later")
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()[:12]
    home = Path(os.environ.get("IMAGE_STUDIO_HOME") or Path.home() / ".image-studio").expanduser()
    binary = home / "bin" / f"mac_vision-{digest}"
    if not binary.is_file():
        swiftc = shutil.which("swiftc")
        if not swiftc:
            raise SystemExit("error: swiftc not found; install the Xcode command line tools: xcode-select --install")
        binary.parent.mkdir(parents=True, exist_ok=True)
        tmp = binary.with_suffix(".tmp")
        build = subprocess.run([swiftc, "-O", str(SOURCE), "-o", str(tmp)], capture_output=True, text=True)
        if build.returncode != 0:
            raise SystemExit("error: building the Vision helper failed:\n" + build.stderr[-800:])
        tmp.replace(binary)
    return binary


def norm(text):
    return re.sub(r"\s+", "", text).casefold()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--timeout", type=int, default=180, help="seconds before giving up (default 180)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("cutout", parents=[common]); p.add_argument("image"); p.add_argument("outdir")
    p.add_argument("--point", nargs=2, type=float, metavar=("X", "Y"))
    p = sub.add_parser("ocr", parents=[common]); p.add_argument("image"); p.add_argument("--expect", action="append", default=[])
    p = sub.add_parser("hands", parents=[common]); p.add_argument("image")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        print("error: --timeout must be a positive number of seconds", file=sys.stderr); return 2
    if not Path(args.image).is_file():
        print(f"error: image not found: {args.image}", file=sys.stderr); return 2
    try: binary = helper()
    except SystemExit as exc:
        print(exc, file=sys.stderr); return 2
    cmd = [str(binary), args.command, args.image]
    if args.command == "cutout":
        cmd.append(args.outdir)
        if args.point: cmd += [str(v) for v in args.point]
    try: run = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        print(f"error: Vision did not answer within {args.timeout} s. The first run on a machine can wait while macOS "
              "prepares its text model; run once more, or raise --timeout.", file=sys.stderr); return 2
    if run.returncode == 2 or not run.stdout.strip():
        print(run.stderr.strip() or "error: the Vision helper failed", file=sys.stderr); return 2
    result = json.loads(run.stdout)
    if args.command == "cutout":
        print(json.dumps(result))
        if run.returncode == 1: print("No subject found" + (" under that point" if args.point else ""), file=sys.stderr)
        return run.returncode
    if args.command == "hands":
        hands = result.get("hands", [])
        for i, hand in enumerate(hands, 1):
            print(f"hand {i}: box {','.join(map(str, hand['box']))}  {hand['joints']}/21 joints  {hand['side']}  "
                  f"confidence {hand['confidence']:.2f}")
        if hands: print("Crop every box at 100% and check fingers, grip, and joints by eye; this list is not a pass.")
        else: print("No hands found (painted hands are often missed: still check them by eye)", file=sys.stderr)
        return run.returncode
    for line in result.get("lines", []):
        print(f"{line['confidence']:.2f}  {','.join(map(str, line['box']))}  {line['text']}")
    if not args.expect: return run.returncode
    found = norm(" ".join(line["text"] for line in result.get("lines", [])))
    missing = [text for text in args.expect if norm(text) not in found]
    for text in missing: print(f"MISSING: {text!r} is not in the image text", file=sys.stderr)
    if not missing: print(f"All {len(args.expect)} expected texts found")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
