#!/usr/bin/env python3
"""Convert an audit contract into an image-loop reviewer brief.

The brief lets `image-loop/scripts/review.py` ask a vision model to judge the same
check IDs; its report.json then feeds `audit_candidate.py --review` unchanged.
"""

import argparse
import json
import sys
from pathlib import Path

from audit_candidate import load_json, validate_contract

KINDS = {"change": "requested", "keep": "protected"}
FORMATS = {"PNG", "JPEG", "WEBP"}


def to_brief(contract, alpha_required=False):
    canvas = contract.get("canvas") if isinstance(contract, dict) else None
    if not isinstance(canvas, dict):
        raise ValueError("contract.canvas must be an object")
    # Repair contracts are checked as if a source of canvas size were supplied.
    size = None if contract.get("mode") == "create" else (canvas.get("width"), canvas.get("height"))
    targets, checks, _, _ = validate_contract(contract, size)
    names = {item["id"]: item["name"] for item in contract["targets"]}
    criteria = []
    for check_id, check in checks.items():
        x, y, width, height = targets[check["target_id"]]
        criteria.append({
            "id": check_id,
            "target": f"{names[check['target_id']]} ({check['target_id']}), source box x={x} y={y} w={width} h={height}",
            "kind": KINDS[check["kind"]],
            "requirement": check["requirement"],
        })
    return {
        "max_repairs": contract.get("max_repairs", 3),
        "name": contract["intent"][:80],
        "intent": contract["intent"],
        "criteria": criteria,
        "file_checks": {"width": canvas["width"], "height": canvas["height"],
                        "format": canvas["format"] if canvas["format"] in FORMATS else None,
                        "alpha_required": alpha_required},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--alpha-required", action="store_true", help="Require real transparent pixels")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output file already exists")
    try:
        brief = to_brief(load_json(args.contract), args.alpha_required)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(f"{type(error).__name__}: {error}")
    args.out.write_text(json.dumps(brief, indent=2) + "\n", encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
