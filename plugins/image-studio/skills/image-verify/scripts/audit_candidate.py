#!/usr/bin/env python3
"""Audit a local image edit against a scene contract and a visual review.

The script never generates pixels or decides what an image depicts. Any nonzero,
non-transparent pixel in an optional acceptance mask permits changes, including a
feathered edge; pure black or fully transparent pixels lock them. Decision names are
shared with image-loop's controller; see references/decisions.md.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path


def load_json(path):
    def reject_constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    def unique_keys(pairs):
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{path}: duplicate JSON keys {sorted({k for k in keys if keys.count(k) > 1})}")
        return dict(pairs)

    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=reject_constant, object_pairs_hook=unique_keys)
        json.dumps(value, ensure_ascii=False).encode("utf-8")  # rejects lone surrogates before anything is written
    except RecursionError:
        raise ValueError(f"{path}: JSON is nested too deeply") from None
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    return value.strip()


def ident(value, label):
    """IDs are compared exactly, so surrounding whitespace is an error rather than silently trimmed."""
    if nonempty(value, label) != value:
        raise ValueError(f"{label} must not start or end with whitespace")
    return value


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
    if type(contract["version"]) is not int or contract["version"] != 1 or contract["mode"] not in ("repair", "create"):
        raise ValueError("contract requires integer version 1 and mode repair or create")
    nonempty(contract["intent"], "intent")
    if contract["mode"] == "repair" and source_size is None:
        raise ValueError("repair mode requires --source")
    if contract["mode"] == "create" and source_size is not None:
        raise ValueError("create mode does not use --source")
    canvas = contract["canvas"]
    exact_fields(canvas, {"width", "height", "format"}, {"alpha_required"}, "canvas")
    if not isinstance(canvas.get("alpha_required", False), bool):
        raise ValueError("canvas.alpha_required must be a boolean")
    for axis in ("width", "height"):
        positive_int(canvas[axis], f"canvas.{axis}")
    nonempty(canvas["format"], "canvas.format")
    if not (canvas["format"].isascii() and canvas["format"].isalnum() and canvas["format"].isupper()):
        raise ValueError("canvas.format must use the decoded uppercase format, such as PNG")
    if canvas["format"] == "JPG":
        raise ValueError("canvas.format: use the decoded format name JPEG, not JPG")
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
        target_id = ident(item["id"], "target.id")
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
        check_id = ident(item["id"], "check.id")
        if check_id in checks or not isinstance(item["target_id"], str) or item["target_id"] not in targets:
            raise ValueError(f"{check_id}: duplicate ID or unknown target")
        if item["kind"] not in ("change", "keep"):
            raise ValueError(f"{check_id}: kind must be change or keep")
        if item["kind"] == "keep" and contract["mode"] == "create":
            raise ValueError(f"{check_id}: keep checks compare against a source; create mode has none, so use change checks")
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
    if "summary" in review and not isinstance(review["summary"], str):
        raise ValueError("review.summary must be a string")  # review.py's schema requires the same
    if not isinstance(items, list):
        raise ValueError("review results must be a list")
    results = {}
    for item in items:
        exact_fields(item, {"id", "status", "evidence"},
                     {"acknowledged_changed_pixels", "suggested_fix", "visible_change_confirmed"}, "review result")
        if "suggested_fix" in item and not isinstance(item["suggested_fix"], str):
            raise ValueError("suggested_fix must be text")
        check_id = ident(item["id"], "result.id")
        if check_id in results or check_id not in checks:
            raise ValueError(f"{check_id}: duplicate or unknown review ID")
        if item["status"] not in ("pass", "fail", "uncertain"):
            raise ValueError(f"{check_id}: invalid status")
        nonempty(item["evidence"], f"{check_id}.evidence")
        if "acknowledged_changed_pixels" in item:
            count = item["acknowledged_changed_pixels"]
            if checks[check_id]["kind"] != "keep" or isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError(f"{check_id}: acknowledged_changed_pixels must be a nonnegative integer on a keep check")
        if "visible_change_confirmed" in item and (checks[check_id]["kind"] != "change"
                                                   or not isinstance(item["visible_change_confirmed"], bool)):
            raise ValueError(f"{check_id}: visible_change_confirmed must be a boolean on a change check")
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


HIGH_PRECISION = {"I", "I;16", "I;16B", "I;16L", "I;16N", "F"}


def reduced_depth(path, image):
    """True when Pillow decoded more than 8 bits per color channel down to 8, so exact comparison is impossible."""
    with open(path, "rb") as stream:
        header = stream.read(26)
    if header[:8] == b"\x89PNG\r\n\x1a\n":
        return header[24] == 16 and header[25] in (2, 4, 6)
    bits = getattr(image, "tag_v2", {}).get(258)  # TIFF BitsPerSample
    return bool(bits) and image.mode not in HIGH_PRECISION and max(bits if isinstance(bits, tuple) else (bits,)) > 8


def open_image(path):
    """Decode an image as displayed (EXIF orientation applied); return it, its file format, and its frame count."""
    from PIL import Image, ImageOps

    try:
        image = Image.open(path)
        image_format, frames = image.format, getattr(image, "n_frames", 1)
        wide = reduced_depth(path, image)
        image = ImageOps.exif_transpose(image)
    except Image.DecompressionBombError as error:
        raise ValueError(f"{path}: {error}") from None
    image.wide_source = wide
    return image, image_format, frames


def editable_mask(image):
    """255 where the final acceptance mask permits change: nonzero luminance and not transparent."""
    from PIL import ImageChops

    from PIL import ImageMath

    if image.mode in HIGH_PRECISION:
        wide = image.convert("F")
        if hasattr(ImageMath, "lambda_eval"):
            return ImageMath.lambda_eval(lambda env: (env["m"] != 0) * 255, m=wide).convert("L")
        return ImageMath.eval("(m != 0) * 255", m=wide).convert("L")
    rgba = image.convert("RGBA")
    red, green, blue, alpha = (band.point(lambda value: 255 if value else 0) for band in rgba.split())
    # Any nonzero color channel permits change, unless that mask pixel is fully transparent.
    return ImageChops.darker(ImageChops.lighter(ImageChops.lighter(red, green), blue), alpha)


def changed_map(source, candidate):
    """255 where the decoded pixels differ, compared without reducing 16-bit or float precision."""
    from PIL import ImageChops, ImageMath

    if source.mode in HIGH_PRECISION or candidate.mode in HIGH_PRECISION:
        # ponytail: single-channel wide compare; 32-bit integers beyond int32 range are not expected in images.
        mode = "F" if "F" in (source.mode, candidate.mode) else "I"
        first, second = source.convert(mode), candidate.convert(mode)
        if hasattr(ImageMath, "lambda_eval"):
            out = ImageMath.lambda_eval(lambda env: (abs(env["a"] - env["b"]) > 0) * 255, a=first, b=second)
        else:
            out = ImageMath.eval("(abs(a - b) > 0) * 255", a=first, b=second)
        return out.convert("L")
    source, candidate = source.convert("RGBA"), candidate.convert("RGBA")
    channels = ImageChops.difference(source, candidate).split()
    changed = channels[0]
    for channel in channels[1:]:
        changed = ImageChops.lighter(changed, channel)
    changed = changed.point(lambda value: 255 if value else 0)
    # Hidden RGB under alpha 0 in both images is invisible, so it is not a change.
    any_alpha = ImageChops.lighter(source.getchannel("A"), candidate.getchannel("A"))
    return ImageChops.darker(changed, any_alpha.point(lambda value: 255 if value else 0))


VISIBLE_DELTA = 8  # 8-bit levels; a smaller difference on every channel is not seen at normal viewing


def visible_map(source, candidate):
    """255 where some 8-bit channel moved by VISIBLE_DELTA or more (wide modes: any change counts)."""
    from PIL import ImageChops

    if source.mode in HIGH_PRECISION or candidate.mode in HIGH_PRECISION:
        return changed_map(source, candidate)
    source, candidate = source.convert("RGBA"), candidate.convert("RGBA")
    channels = ImageChops.difference(source, candidate).split()
    largest = channels[0]
    for channel in channels[1:]:
        largest = ImageChops.lighter(largest, channel)
    any_alpha = ImageChops.lighter(source.getchannel("A"), candidate.getchannel("A")).point(lambda v: 255 if v else 0)
    return ImageChops.darker(largest.point(lambda v: 255 if v >= VISIBLE_DELTA else 0), any_alpha)


def inspect_pixels(source, candidate, mask, targets):
    from PIL import ImageChops

    changed, visible = changed_map(source, candidate), visible_map(source, candidate)
    counts, seen = {}, {}
    for target_id, (x, y, width, height) in targets.items():
        box = (x, y, x + width, y + height)
        counts[target_id] = changed.crop(box).histogram()[255]
        seen[target_id] = visible.crop(box).histogram()[255]
    outside = None
    if mask is not None:
        outside = ImageChops.darker(changed, ImageChops.invert(mask)).histogram()[255]
    return {"changed_pixels": changed.histogram()[255], "changed_by_target": counts,
            "visible_by_target": seen, "changed_outside_mask": outside}


def too_small_changes(checks, results, pixels, targets):
    """Passed change checks whose target barely changed visibly; a person must confirm them."""
    if pixels is None:
        return {}
    found = {}
    for check_id, item in checks.items():
        result = results[check_id]
        if item["kind"] != "change" or result["status"] != "pass" or result.get("visible_change_confirmed"):
            continue
        _, _, width, height = targets[item["target_id"]]
        seen = pixels["visible_by_target"][item["target_id"]]
        if seen < max(4, width * height // 200):  # under 0.5% of the target box
            found[check_id] = seen
    return found


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


def decide(checks, results, technical_issues, repairs_used, max_repairs, previous, keep_changes=None, small_changes=None):
    """Same order and action names as image-loop's controller.decide (references/decisions.md)."""
    if technical_issues:
        return {"action": "reject_technical", "reason": "File or pixel checks failed.", "issues": technical_issues}
    uncertain = [item["id"] for item in results.values() if item["status"] == "uncertain"]
    if uncertain or keep_changes or small_changes:
        decision = {"action": "hold_for_inspection", "reason": "Evidence needs stronger inspection.",
                    "ids": uncertain + sorted(keep_changes or {}) + sorted(small_changes or {})}
        if keep_changes:
            decision["changed_keep_pixels"] = keep_changes
        if small_changes:
            decision["barely_visible_change_pixels"] = small_changes
        return decision
    failed = [item["id"] for item in results.values() if item["status"] == "fail"]
    if not failed:
        return {"action": "accepted_by_checks", "reason": "All specified checks passed.", "ids": []}
    if repairs_used >= max_repairs:
        return {"action": "stop_budget", "reason": "Repair limit reached.", "ids": failed}
    if previous is not None:
        old = {item["id"] for item in previous.values() if item["status"] == "fail"}
        if old == set(failed):
            return {"action": "stop_repeated_failure", "reason": "Same failure set persisted after a repair.", "ids": sorted(old)}
    return {"action": "repair", "reason": "Repair only the failed checks; recheck all checks.", "ids": failed,
            "protected_failed": [check_id for check_id in failed if checks[check_id]["kind"] == "keep"],
            "start_from": "last accepted clean source or candidate; never this candidate if protected_failed is not empty"}


def repair_prompt(contract, targets, checks, results, decision):
    """Instruction for the host image tool that names failed checks by source-pixel location."""
    names = {item["id"]: item["name"] for item in contract["targets"]}

    def where(target_id):
        x, y, width, height = targets[target_id]
        return f"{names[target_id]} ({target_id}) at source box x={x}, y={y}, width={width}, height={height}"

    lines = ["Edit the supplied clean source image. Intent: " + contract["intent"], "", "Correct only these failed checks:"]
    for check_id in decision["ids"]:
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
    parser.add_argument("--repairs-used", type=int,
                        help="Optional cross-check; derived from --previous (previous round + 1), else 0")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output directory already exists; keep each round separate")
    try:
        import PIL  # noqa: F401
    except ImportError:
        parser.error("Pillow is required for decoded image and pixel checks: python3 -m pip install pillow")
    try:
        contract = load_json(args.contract)
        review = load_json(args.review)
        source, _, source_frames = open_image(args.source) if args.source else (None, None, 1)
        candidate, candidate_format, candidate_frames = open_image(args.candidate)
        if source_frames > 1:
            raise ValueError("the source is animated; audit one still frame")
        source_size = source.size if source else None
        targets, checks, locked, limit = validate_contract(contract, source_size)
        results = validate_review(review, checks)
        previous, repairs_used = None, 0
        if args.previous:
            if not args.previous.exists():
                raise ValueError(f"--previous {args.previous} does not exist")
            folder = args.previous if args.previous.is_dir() else args.previous.parent
            prior_evidence = load_json(folder / "evidence.json")
            if (prior_evidence.get("contract_sha256") != digest(args.contract)
                    or prior_evidence.get("source_sha256") != (digest(args.source) if args.source else None)):
                raise ValueError("previous round uses a different contract or source")
            prior_action = load_json(folder / "decision.json").get("action")
            if prior_action != "repair":
                raise ValueError(f"previous round decided {prior_action!r}; only a repair decision starts another round")
            prior_count = prior_evidence.get("repairs_used")
            if type(prior_count) is not int or prior_count < 0:
                raise ValueError("previous evidence.json has no valid repairs_used; start again from round 0")
            repairs_used = prior_count + 1
            previous = validate_review(load_json(folder / "review.json"), checks)
        if args.repairs_used is not None and args.repairs_used != repairs_used:
            raise ValueError(f"--repairs-used {args.repairs_used} does not match the round history ({repairs_used})")
        if locked != bool(args.mask):
            raise ValueError("--mask is required exactly when pixel_lock_outside_mask is true")
        issues = []
        mask = None
        if args.mask:
            mask_image = open_image(args.mask)[0]
            if mask_image.wide_source:
                raise ValueError("the mask is a 16-bit-per-channel color image; save it as 8-bit or grayscale")
            mask = editable_mask(mask_image)
            if mask.size != candidate.size:
                issues.append("acceptance mask dimensions differ from the candidate")
                mask = None
        canvas = contract["canvas"]
        if candidate.size != (canvas["width"], canvas["height"]):
            issues.append("candidate dimensions differ from the contract")
        if candidate_format != canvas["format"]:
            issues.append("candidate decoded format differs from the contract")
        if candidate_frames > 1:
            issues.append("candidate is animated; only its first frame could be checked")
        if canvas.get("alpha_required") and (candidate.mode not in ("RGBA", "LA", "PA") and "transparency" not in candidate.info
                                             or candidate.convert("RGBA").getchannel("A").getextrema()[0] == 255):
            issues.append("candidate has no transparent pixels but the contract requires transparency")
        if source and candidate.size != source.size:
            issues.append("source and candidate dimensions differ; source-coordinate comparison is invalid")
        for label, image in (("source", source), ("candidate", candidate)):
            if image is not None and image.wide_source:
                issues.append(f"{label} has 16 bits per color channel; Pillow reads it as 8-bit, so exact comparison "
                              "is not possible. Compare 8-bit or 16-bit grayscale copies instead.")
        if source and (source.mode in HIGH_PRECISION) != (candidate.mode in HIGH_PRECISION):
            issues.append(f"source ({source.mode}) and candidate ({candidate.mode}) bit depth differ")
        pixels = None
        if source and source.size == candidate.size and (mask is not None or not locked):
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
                                  "format": candidate_format, "mode": candidate.mode}, "pixels": pixels,
                    "repairs_used": repairs_used, "max_repairs": limit,
                    "technical_issues": issues}
        decision = decide(checks, results, issues, repairs_used, limit, previous,
                          unacknowledged_keep_changes(checks, results, pixels),
                          too_small_changes(checks, results, pixels, targets))
        files = {"evidence.json": evidence, "decision.json": decision, "review.json": review}
        files = {name: json.dumps(value, indent=2) + "\n" for name, value in files.items()}
        if decision["action"] == "repair":
            files["repair-prompt.txt"] = repair_prompt(contract, targets, checks, results, decision)
        args.out.mkdir(parents=True)
        for name, text in files.items():
            (args.out / name).write_text(text, encoding="utf-8")
        print(json.dumps(decision))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.error(f"{type(error).__name__}: {error}")


if __name__ == "__main__":
    sys.exit(main())
