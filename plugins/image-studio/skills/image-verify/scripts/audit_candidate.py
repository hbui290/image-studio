#!/usr/bin/env python3
"""Audit a local image edit against a scene contract and a visual review.

The script never generates pixels or decides what an image depicts. Any nonzero
pixel in an optional acceptance mask permits changes, including a feathered edge;
pure black pixels lock them.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path


def load_json(path):
    def reject_constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    return value.strip()


def exact_fields(value, required, optional, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing or extra:
        raise ValueError(f"{label}: missing {sorted(missing)}, unknown {sorted(extra)}")


def positive_int(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def validate_contract(contract, source_size):
    exact_fields(contract, {"version", "mode", "intent", "canvas", "targets", "checks"},
                 {"pixel_lock_outside_mask", "max_repairs"}, "contract")
    if contract["version"] != 1 or contract["mode"] not in {"repair", "create"}:
        raise ValueError("contract requires version 1 and mode repair or create")
    nonempty(contract["intent"], "intent")
    if contract["mode"] == "repair" and source_size is None:
        raise ValueError("repair mode requires --source")
    if contract["mode"] == "create" and source_size is not None:
        raise ValueError("create mode does not use --source")
    canvas = contract["canvas"]
    exact_fields(canvas, {"width", "height", "format"}, set(), "canvas")
    for axis in ("width", "height"):
        positive_int(canvas[axis], f"canvas.{axis}")
    nonempty(canvas["format"], "canvas.format")
    if canvas["format"] != canvas["format"].upper():
        raise ValueError("canvas.format must use the decoded uppercase format, such as PNG")
    if source_size and source_size != (canvas["width"], canvas["height"]):
        raise ValueError("source dimensions differ from contract canvas; update the contract")
    locked = contract.get("pixel_lock_outside_mask", False)
    if not isinstance(locked, bool) or (locked and source_size is None):
        raise ValueError("pixel_lock_outside_mask must be a boolean and requires a source")
    limit = contract.get("max_repairs", 3)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("max_repairs must be a nonnegative integer")
    if not isinstance(contract["targets"], list) or not isinstance(contract["checks"], list) or not contract["checks"]:
        raise ValueError("targets must be a list and checks must be a nonempty list")
    targets = {}
    for item in contract["targets"]:
        exact_fields(item, {"id", "name", "bbox"}, set(), "target")
        target_id = nonempty(item["id"], "target.id")
        nonempty(item["name"], "target.name")
        box = item["bbox"]
        if target_id in targets or not isinstance(box, list) or len(box) != 4:
            raise ValueError(f"{target_id}: duplicate ID or invalid bbox")
        if any(isinstance(n, bool) or not isinstance(n, int) for n in box):
            raise ValueError(f"{target_id}: bbox must contain source-pixel integers")
        x, y, width, height = box
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > canvas["width"] or y + height > canvas["height"]:
            raise ValueError(f"{target_id}: bbox falls outside the canvas")
        targets[target_id] = box
    checks = {}
    for item in contract["checks"]:
        exact_fields(item, {"id", "target_id", "kind", "requirement"}, set(), "check")
        check_id = nonempty(item["id"], "check.id")
        if check_id in checks or item["target_id"] not in targets:
            raise ValueError(f"{check_id}: duplicate ID or unknown target")
        if item["kind"] not in {"change", "keep"}:
            raise ValueError(f"{check_id}: kind must be change or keep")
        nonempty(item["requirement"], f"{check_id}.requirement")
        checks[check_id] = item
    return targets, checks, locked, limit


def validate_review(review, checks):
    """Accept this helper's `results` review or an image-loop reviewer `criteria` report."""
    if "criteria" in review:
        exact_fields(review, {"criteria"}, {"summary", "reviewer"}, "review")
        items = review["criteria"]
    else:
        exact_fields(review, {"results"}, {"reviewer"}, "review")
        items = review["results"]
    if "reviewer" in review:
        nonempty(review["reviewer"], "reviewer")
    if not isinstance(items, list):
        raise ValueError("review results must be a list")
    results = {}
    for item in items:
        exact_fields(item, {"id", "status", "evidence"}, {"acknowledged_changed_pixels", "suggested_fix"}, "review result")
        if "suggested_fix" in item and not isinstance(item["suggested_fix"], str):
            raise ValueError("suggested_fix must be text")
        check_id = nonempty(item["id"], "result.id")
        if check_id in results or check_id not in checks:
            raise ValueError(f"{check_id}: duplicate or unknown review ID")
        if item["status"] not in {"pass", "fail", "uncertain"}:
            raise ValueError(f"{check_id}: invalid status")
        nonempty(item["evidence"], f"{check_id}.evidence")
        if "acknowledged_changed_pixels" in item:
            count = item["acknowledged_changed_pixels"]
            if checks[check_id]["kind"] != "keep" or isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError(f"{check_id}: acknowledged_changed_pixels must be a nonnegative integer on a keep check")
        results[check_id] = item
    if results.keys() != checks.keys():
        raise ValueError(f"review is missing IDs: {sorted(checks.keys() - results.keys())}")
    return results


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def inspect_pixels(source, candidate, mask, targets):
    from PIL import ImageChops

    source, candidate = source.convert("RGBA"), candidate.convert("RGBA")
    delta = ImageChops.difference(source, candidate)
    channels = delta.split()
    changed = channels[0]
    for channel in channels[1:]:
        changed = ImageChops.lighter(changed, channel)
    changed = changed.point(lambda value: 255 if value else 0)
    # Hidden RGB under alpha 0 in both images is invisible, so it is not a change.
    any_alpha = ImageChops.lighter(source.getchannel("A"), candidate.getchannel("A"))
    changed = ImageChops.darker(changed, any_alpha.point(lambda value: 255 if value else 0))
    counts = {}
    for target_id, (x, y, width, height) in targets.items():
        counts[target_id] = changed.crop((x, y, x + width, y + height)).histogram()[255]
    outside = None
    if mask is not None:
        outside = ImageChops.darker(changed, ImageChops.invert(mask)).histogram()[255]
    return {"changed_pixels": changed.histogram()[255], "changed_by_target": counts,
            "changed_outside_mask": outside}


def unacknowledged_keep_changes(checks, results, pixels):
    """Passed keep checks whose target changed more pixels than the reviewer acknowledged."""
    if pixels is None:
        return {}
    found = {}
    for check_id, item in checks.items():
        changed = pixels["changed_by_target"][item["target_id"]]
        result = results[check_id]
        if item["kind"] == "keep" and result["status"] == "pass" and changed > result.get("acknowledged_changed_pixels", 0):
            found[check_id] = changed
    return found


def decide(checks, results, technical_issues, repairs_used, max_repairs, previous, keep_changes=None):
    if technical_issues:
        return {"action": "reject_technical", "issues": technical_issues}
    uncertain = [item["id"] for item in results.values() if item["status"] == "uncertain"]
    if uncertain or keep_changes:
        decision = {"action": "hold_for_inspection", "check_ids": uncertain + sorted(keep_changes or {})}
        if keep_changes:
            decision["changed_keep_pixels"] = keep_changes
        return decision
    failed = [item["id"] for item in results.values() if item["status"] == "fail"]
    protected = [check_id for check_id in failed if checks[check_id]["kind"] == "keep"]
    if protected:
        return {"action": "reject_protected", "check_ids": protected}
    if not failed:
        return {"action": "accepted_by_checks", "check_ids": []}
    if repairs_used >= max_repairs:
        return {"action": "stop_limit", "check_ids": failed}
    if previous:
        old = {item["id"] for item in previous.values() if item["status"] == "fail"}
        if old == set(failed):
            return {"action": "stop_repeated_failure", "check_ids": failed}
    return {"action": "repair", "check_ids": failed,
            "reinspect_ids": list(checks), "start_from": "last accepted clean source or candidate"}


def repair_prompt(contract, targets, checks, results, decision):
    """Instruction for the host image tool that names failed checks by source-pixel location."""
    names = {item["id"]: item["name"] for item in contract["targets"]}

    def where(target_id):
        x, y, width, height = targets[target_id]
        return f"{names[target_id]} ({target_id}) at source box x={x}, y={y}, width={width}, height={height}"

    lines = ["Edit the supplied clean source image. Intent: " + contract["intent"], "", "Correct only these failed checks:"]
    for check_id in decision["check_ids"]:
        check, result = checks[check_id], results[check_id]
        lines += [f"- {check_id}: {check['requirement']} ({where(check['target_id'])})",
                  f"  Reviewer observation: {result['evidence']}"]
        if result.get("suggested_fix"):
            lines.append(f"  Suggested minimal fix: {result['suggested_fix']}")
    lines += ["", "Keep these unchanged:"]
    lines += [f"- {check_id}: {item['requirement']} ({where(item['target_id'])})"
              for check_id, item in checks.items() if item["kind"] == "keep"]
    canvas = contract["canvas"]
    lines += ["", f"Output: {canvas['width']}x{canvas['height']} {canvas['format']}.",
              "Do not add review badges, numbering, or annotation arrows."]
    if contract.get("pixel_lock_outside_mask"):
        lines.append("Pixels outside the final acceptance mask will be restored from the source; change only the masked region.")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("contract", "candidate", "review", "out"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    for name in ("source", "mask", "previous"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--repairs-used", type=int, default=0)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output directory already exists; keep each round separate")
    if args.repairs_used < 0 or bool(args.repairs_used) != bool(args.previous):
        parser.error("use --previous and a positive --repairs-used together")
    try:
        from PIL import Image
    except ImportError:
        parser.error("Pillow is required for decoded image and pixel checks")
    try:
        contract = load_json(args.contract)
        review = load_json(args.review)
        source = Image.open(args.source) if args.source else None
        candidate = Image.open(args.candidate)
        source_size = source.size if source else None
        targets, checks, locked, limit = validate_contract(contract, source_size)
        results = validate_review(review, checks)
        previous = None
        if args.previous:
            prior_evidence = load_json(args.previous / "evidence.json")
            if (prior_evidence.get("contract_sha256") != digest(args.contract)
                    or prior_evidence.get("source_sha256") != (digest(args.source) if args.source else None)):
                raise ValueError("previous round uses a different contract or source")
            previous = validate_review(load_json(args.previous / "review.json"), checks)
        if locked != bool(args.mask):
            raise ValueError("--mask is required exactly when pixel_lock_outside_mask is true")
        mask = Image.open(args.mask).convert("L") if args.mask else None
        if mask and mask.size != candidate.size:
            raise ValueError("acceptance mask dimensions differ from the candidate")
        if mask:
            # A feathered edge is editable: every nonzero pixel permits change, only pure black locks.
            mask = mask.point(lambda value: 255 if value else 0)
        issues = []
        canvas = contract["canvas"]
        if candidate.size != (canvas["width"], canvas["height"]):
            issues.append("candidate dimensions differ from the contract")
        if candidate.format != canvas["format"]:
            issues.append("candidate decoded format differs from the contract")
        if source and candidate.size != source.size:
            issues.append("source and candidate dimensions differ; source-coordinate comparison is invalid")
        pixels = None
        if source and source.size == candidate.size:
            pixels = inspect_pixels(source, candidate, mask, targets)
            if locked and pixels["changed_outside_mask"]:
                issues.append("decoded pixels changed outside the acceptance mask")
            for check_id, item in checks.items():
                if item["kind"] == "change" and results[check_id]["status"] == "pass" and not pixels["changed_by_target"][item["target_id"]]:
                    issues.append(f"{check_id}: reported change has no decoded pixel difference inside its target")
        evidence = {"contract_sha256": digest(args.contract),
                    "source_sha256": digest(args.source) if args.source else None,
                    "candidate_sha256": digest(args.candidate),
                    "mask_sha256": digest(args.mask) if args.mask else None,
                    "candidate": {"width": candidate.width, "height": candidate.height,
                                  "format": candidate.format}, "pixels": pixels,
                    "technical_issues": issues}
        decision = decide(checks, results, issues, args.repairs_used, limit, previous,
                          unacknowledged_keep_changes(checks, results, pixels))
        args.out.mkdir(parents=True)
        (args.out / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        (args.out / "decision.json").write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
        (args.out / "review.json").write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
        if decision["action"] == "repair":
            (args.out / "repair-prompt.txt").write_text(
                repair_prompt(contract, targets, checks, results, decision), encoding="utf-8")
        print(json.dumps(decision))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    sys.exit(main())
