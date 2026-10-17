#!/usr/bin/env python3
"""Project memory and evidence gate for image-studio.

Keeps a per-project store in `<project>/.image-studio/` (approved deliverables, master
files, user decisions, and every defect ever reported) and a bounded user preference
file in `${IMAGE_STUDIO_HOME:-~/.image-studio}`. The `gate` subcommand is the only way
to prove a deliverable is done: the file must be the approved one, match its spec, pass
objective logo checks, every resolved defect must show changed pixels, and every
recorded defect needs a verdict that names a crop made in the same gate run.
`hook session-start` and `hook stop` are thin wrappers for Claude Code and Codex plugin
hooks; they always exit 0 and print nothing on errors.

Exit codes: 0 success or gate pass, 1 gate fail, 2 bad input or missing store.
"""

import argparse
import hashlib
import io
import json
import os
import re
import secrets
import shlex
import sys
import tempfile
import time
import types
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

STORE_DIR = ".image-studio"
SCHEMA_VERSION = 1
PREF_CAP = 1500
CROP_MARGIN = 16
MIN_EVIDENCE = 10
DEFAULT_IOU = 0.90
NOTE_LIMIT = 120
MIN_BOX = 16           # smallest defect box side (px) without a user quote
MIN_BOX_SHARE = 0.001  # smallest defect box area (share of the image) without a user quote
CHANGE_LEVEL = 8       # per-channel difference that counts as a changed pixel
MIN_CHANGED = 0.05     # share of changed pixels a resolved defect's box needs
MAX_MEMBER_BYTES = 256 << 20
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DEFECT_ID_RE = re.compile(r"^D([1-9][0-9]*)$")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
KINDS = ("logo", "seam", "artifact", "scope", "color", "other")
ROLES = ("shape", "color", "logo", "layout")
ALPHA_RULES = ("required", "forbidden", "any")
FORMATS = {"PNG": "PNG", "JPEG": "JPEG", "JPG": "JPEG", "WEBP": "WEBP", "ZIP": "ZIP"}
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PREF_LINE = re.compile(r"^- \[(confirmed|proposed)\] (.+)$")
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_HINT = "python3 " + shlex.quote(os.path.abspath(__file__))  # real path: agents cannot resolve doc placeholders

# Final messages allowed while a gate is missing: an honest report with all three headings, or a question.
REPORT_HEADINGS = tuple(re.compile(r"(?:^|[\n.;|])\s*[\s#*>_|-]*(" + words + r")[*_]*\s*(:|\s*$)", re.I | re.M) for words in
                        ("checked|đã kiểm", "not checked|chưa kiểm", "still failing|còn lỗi"))

COMPLETION_WORDS = (
    "done",
    r"complete(?:d)?",
    "finished",
    "fixed",
    "verified",
    "ready",
    r"all\s+set",
    r"all\s+good",
    r"looks\s+good",
    r"looks\s+great",
    "final",
    "shipped",
    "delivered",
    "exported",
    r"hoàn\s+thành",
    r"hoàn\s+tất",
    "xong",
    r"đã\s+sửa",
    "✅",
)
COMPLETION_RE = re.compile(
    r"(?:\b(?:" + "|".join(w for w in COMPLETION_WORDS if w != "✅") + r")\b|✅)",
    re.IGNORECASE | re.UNICODE,
)


def valid_session_id(session_id):
    return (
        isinstance(session_id, str)
        and session_id not in (".", "..")
        and bool(SESSION_ID_RE.match(session_id))
    )

# Logo check tuning.
STROKE_TOL = 60     # max-channel distance that still counts as a master stroke colour
BAND = 12           # width of the background band just outside the bbox
SPECK = 6           # master components smaller than this many pixels (at master scale) are ignored
ASPECT_TOL = 0.10
BUSY_BASELINE = 0.05
EXTRA_STROKES = 0.05   # duplicate-logo pixels outside the placed master, as a share of the logo area
LOOKALIKE_SHARE = 0.02  # band pixels sharing a stroke colour above this: busy background
LOGO_MAX_SIDE = 640
SENTINELS = ((255, 0, 255), (0, 255, 0), (255, 255, 0), (0, 255, 255))


class UsageError(Exception):
    """Bad input or missing store: reported as one line and exit code 2."""


# ---------------------------------------------------------------- small helpers

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path, data):
    """Write text or bytes via temp file + rename so a crash never leaves a half file."""
    path = Path(path)
    payload = data.encode("utf-8") if isinstance(data, str) else data
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def dump_json(value):
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def read_json(path, label):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise UsageError(f"{path}: missing {label}") from None
    except (ValueError, UnicodeDecodeError) as exc:
        raise UsageError(f"{path}: {label} is not valid JSON ({exc})") from None
    if not isinstance(value, dict):
        raise UsageError(f"{path}: {label} must be a JSON object")
    return value


def ident(value, label):
    if not isinstance(value, str) or not ID_RE.match(value):
        raise UsageError(f"{label} {value!r} must be 1-64 letters, digits, '.', '_' or '-' and start with a letter or digit")
    return value


def text_arg(value, label, required=True):
    value = (value or "").strip()
    if required and not value:
        raise UsageError(f"{label} must be nonempty text")
    if "\n" in value or "\r" in value:
        raise UsageError(f"{label} must be a single line")
    return value


def short(text, limit=NOTE_LIMIT):
    text = str(text or "")
    return text if len(text) <= limit else text[:limit - 3] + "..."


def plugin_version():
    for manifest in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        try:
            version = json.loads((PLUGIN_ROOT / manifest).read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(version, str) and version:
            return version
    return None


def user_home():
    return Path(os.environ.get("IMAGE_STUDIO_HOME") or (Path.home() / STORE_DIR)).expanduser()


def pil():
    """Pillow modules, imported lazily so the hooks and text commands work without Pillow."""
    try:
        from PIL import Image, ImageChops, ImageFilter, ImageStat, PngImagePlugin
    except ImportError:
        raise UsageError("Pillow is required: uv run --with pillow python3 ... (or pip install pillow)") from None
    resampling = getattr(Image, "Resampling", Image)
    return types.SimpleNamespace(Image=Image, ImageChops=ImageChops, ImageFilter=ImageFilter, ImageStat=ImageStat,
                                 PngImagePlugin=PngImagePlugin, NEAREST=resampling.NEAREST,
                                 BILINEAR=resampling.BILINEAR)


def spec_text(spec):
    return f"{spec.get('width')}x{spec.get('height')} {spec.get('format')} alpha {spec.get('alpha')}"


# ---------------------------------------------------------------- store

class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.project = self.root.parent
        self.state_path = self.root / "state.json"
        self.defects_path = self.root / "defects.jsonl"
        self.state = self._load_state()

    def _load_state(self):
        state = read_json(self.state_path, "state.json")
        for key, kind in (("deliverables", dict), ("masters", dict), ("decisions", list), ("brand", str)):
            if not isinstance(state.get(key), kind):
                raise UsageError(f"{self.state_path}: state.json field {key!r} is missing or has the wrong type")
        if not isinstance(state.get("gates"), dict):
            state["gates"] = {}
        return state

    def save(self):
        atomic_write(self.state_path, dump_json(self.state))

    def defects(self):
        if not self.defects_path.exists():
            return []
        items = []
        for number, line in enumerate(self.defects_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError:
                raise UsageError(f"{self.defects_path}:{number}: not valid JSON") from None
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise UsageError(f"{self.defects_path}:{number}: defect must be an object with an id")
            items.append(item)
        return items

    def save_defects(self, items):
        atomic_write(self.defects_path, "".join(json.dumps(i, sort_keys=True, ensure_ascii=False) + "\n" for i in items))

    def resolve(self, stored):
        path = Path(stored)
        return path if path.is_absolute() else self.project / path

    def relative(self, path):
        path = Path(path).resolve()
        try:
            return path.relative_to(self.project.resolve()).as_posix()
        except ValueError:
            return str(path)

    def decide(self, text, quote):
        self.state["decisions"].append({"time": now(), "text": text, "quote": quote or ""})

    def deliverable(self, name):
        item = self.state["deliverables"].get(name)
        if not isinstance(item, dict):
            known = ", ".join(sorted(self.state["deliverables"])) or "none"
            raise UsageError(f"unknown deliverable {name!r} (known: {known}); run approve deliverable first")
        return item


def find_store(start):
    """Walk up from start to the nearest .image-studio/ with a state.json; never the user home."""
    try:
        home = user_home().resolve()
    except (OSError, RuntimeError):
        home = None
    path = Path(start).expanduser().resolve()
    for folder in [path] + list(path.parents):
        candidate = folder / STORE_DIR
        if home is not None and candidate.resolve() == home:
            continue
        if (candidate / "state.json").is_file():
            return candidate
    return None


def open_store(project):
    start = Path(project).expanduser() if project else Path.cwd()
    if project and not start.is_dir():
        raise UsageError(f"--project {project} is not a folder")
    root = find_store(start)
    if root is None:
        raise UsageError(f"no {STORE_DIR}/ store found from {start.resolve()} upward; "
                         f"run: {SCRIPT_HINT} init --project PATH --brand ID")
    return Store(root)


# ---------------------------------------------------------------- images

def has_alpha(img):
    return img.mode in ("RGBA", "LA", "PA", "RGBa", "La") or "transparency" in img.info


def load_image(data):
    P = pil()
    with P.Image.open(io.BytesIO(data)) as img:
        img.load()
        fmt = img.format
        copy = img.copy()
    copy.format = fmt
    return copy


def open_image(path, member=None):
    """Load an image fully (from a file or one ZIP member, by name or ZipInfo) detached from the file."""
    if member is None:
        return load_image(Path(path).read_bytes())
    with zipfile.ZipFile(path) as archive:
        info = member if isinstance(member, zipfile.ZipInfo) else archive.getinfo(member)
        if info.file_size > MAX_MEMBER_BYTES:
            raise ValueError(f"{info.filename} is larger than {MAX_MEMBER_BYTES >> 20} MB")
        data = archive.read(info)
    return load_image(data)


def memory_paths(names):
    """Member names that are project memory: any .image-studio segment (any case), or state.json next to
    defects.jsonl in the same folder."""
    found = []
    folders = {}
    for name in names:
        parts = PurePosixPath(name.replace("\\", "/")).parts
        if STORE_DIR in (part.lower() for part in parts):
            found.append(name)
        elif parts:
            folders.setdefault(parts[:-1], {})[parts[-1].lower()] = name
    for files in folders.values():
        if "state.json" in files and "defects.jsonl" in files:
            found += [files["state.json"], files["defects.jsonl"]]
    return found


def zip_images(path):
    """(names, problems): every ZIP member Pillow can open, whatever its extension."""
    names, problems = [], []
    with zipfile.ZipFile(path) as archive:
        members = [i for i in archive.infolist() if not i.is_dir()]
    for info in members:
        try:
            open_image(path, info)
        except Exception as exc:
            suffix = PurePosixPath(info.filename).suffix.lower()
            if suffix in IMAGE_SUFFIXES or not suffix:
                problems.append(f"{info.filename}: cannot open as image ({exc})")
            continue
        names.append(info.filename)
    return names, problems


def target_image(path, spec, defect):
    """The image a defect's bbox refers to: the file itself, or one image inside a ZIP deliverable."""
    member = defect.get("member")
    if spec.get("format") == "ZIP" and member is None:
        names = zip_images(path)[0]
        if len(names) != 1:
            raise ValueError("ZIP deliverable has several images; the defect needs --member")
        member = names[0]
    return open_image(path, member if spec.get("format") == "ZIP" else None)


def region_crop(img, bbox):
    x0, y0, x1, y1 = bbox
    box = (min(x0, img.size[0]), min(y0, img.size[1]), min(x1, img.size[0]), min(y1, img.size[1]))
    return img.crop(box).convert("RGBA")


def region_hash(img, bbox):
    """Hash of the decoded pixels inside bbox (format and metadata do not matter)."""
    crop = region_crop(img, bbox)
    return sha256_bytes(f"{crop.size[0]}x{crop.size[1]}:".encode() + crop.tobytes())


def changed_share(before, after):
    """Share of pixels whose largest per-channel difference (alpha included) exceeds CHANGE_LEVEL."""
    P = pil()
    if before.size != after.size:
        return 1.0
    bands = P.ImageChops.difference(before.convert("RGBA"), after.convert("RGBA")).split()
    peak = bands[0]
    for band in bands[1:]:
        peak = P.ImageChops.lighter(peak, band)
    total = before.size[0] * before.size[1]
    return count_on(peak.point(lambda v: 255 if v > CHANGE_LEVEL else 0)) / float(total or 1)


def alpha_problem(img, rule):
    transparent = False
    if has_alpha(img):
        transparent = img.convert("RGBA").getchannel("A").getextrema()[0] < 255
    if rule == "required" and not transparent:
        return "alpha required but the image has no transparent pixels"
    if rule == "forbidden" and transparent:
        return "alpha forbidden but the image has transparent pixels"
    return None


def image_problems(img, spec, label):
    problems = []
    if img.size != (spec.get("width"), spec.get("height")):
        problems.append(f"{label}: size {img.size[0]}x{img.size[1]}, spec {spec.get('width')}x{spec.get('height')}")
    issue = alpha_problem(img, spec.get("alpha", "any"))
    if issue:
        problems.append(f"{label}: {issue}")
    return problems


# ---------------------------------------------------------------- init / approve / defect

def cmd_init(args):
    brand = ident(args.brand, "--brand")
    project = Path(args.project).expanduser()
    if not project.is_dir():
        raise UsageError(f"--project {project} is not an existing folder")
    project = project.resolve()
    root = project / STORE_DIR
    if project == Path.home().resolve() or root.resolve() == user_home().resolve():
        raise UsageError("refusing to create a project store in the home folder; pass the project folder with --project")
    ancestor = find_store(project.parent) if project.parent != project else None
    if ancestor is not None:
        raise UsageError(f"{ancestor} already covers this folder; use that store (or pass its project) instead of "
                         "creating a nested one")
    if (root / "state.json").exists():
        store = Store(root)
        if store.state["brand"] != brand:
            raise UsageError(f"{root} already exists for brand {store.state['brand']!r}, not {brand!r}")
        print(root)
        return 0
    (root / "masters").mkdir(parents=True, exist_ok=True)
    state = {"schema_version": SCHEMA_VERSION, "plugin_version_last_seen": plugin_version() or "unknown",
             "brand": brand, "deliverables": {}, "masters": {}, "decisions": [], "gates": {}}
    atomic_write(root / "state.json", dump_json(state))
    if not (root / "defects.jsonl").exists():
        atomic_write(root / "defects.jsonl", "")
    print(root)
    return 0


def existing_file(value, label):
    path = Path(value).expanduser()
    if not path.is_file():
        raise UsageError(f"{label} {value} is not an existing file")
    return path


def cmd_approve_master(args):
    store = open_store(args.project)
    name = ident(args.name, "--name")
    source = existing_file(args.file, "--file")
    data = source.read_bytes()
    try:
        load_image(data)
    except UsageError:
        raise
    except Exception as exc:
        raise UsageError(f"--file {source} is not a readable image ({exc})") from None
    target = store.root / "masters" / (name + source.suffix.lower())
    previous = store.state["masters"].get(name)
    quote = text_arg(args.quote, "--quote", False)
    digest = sha256_bytes(data)
    replaced = list(previous.get("replaced") or []) if isinstance(previous, dict) else []
    if isinstance(previous, dict) and previous.get("sha256") != digest:
        if not quote:
            raise UsageError(f"master {name!r} already exists with another file; replacing it needs --quote with the "
                             "user's words")
        replaced.append({"time": now(), "previous_sha256": previous.get("sha256"), "sha256": digest, "quote": quote})
    atomic_write(target, data)
    if isinstance(previous, dict) and previous.get("path") and store.root / previous["path"] != target:
        try:
            (store.root / previous["path"]).unlink()
        except OSError:
            pass
    store.state["masters"][name] = {"path": target.relative_to(store.root).as_posix(), "sha256": digest,
                                    "role": args.role, "note": text_arg(args.note, "--note", False),
                                    "approved_quote": quote}
    if replaced:
        store.state["masters"][name]["replaced"] = replaced
    store.decide(f"approved master {name} ({args.role}) from {source.name}", quote)
    store.save()
    print(f"Approved master {name} [{args.role}] sha256 {store.state['masters'][name]['sha256']}")
    return 0


def cmd_approve_deliverable(args):
    store = open_store(args.project)
    name = ident(args.name, "--name")
    path = existing_file(args.file, "--file")
    previous = store.state["deliverables"].get(name) or {}
    old_spec = dict(previous.get("spec") or {})
    spec = dict(old_spec)
    for key in ("width", "height"):
        value = getattr(args, key)
        if value is not None:
            if value <= 0:
                raise UsageError(f"--{key} must be a positive integer")
            spec[key] = value
    if args.format is not None:
        fmt = FORMATS.get(args.format.upper())
        if fmt is None:
            raise UsageError(f"--format must be one of {', '.join(sorted(set(FORMATS.values())))}")
        spec["format"] = fmt
    if args.alpha is not None:
        spec["alpha"] = args.alpha
    spec.setdefault("alpha", "any")
    missing = [k for k in ("width", "height", "format") if k not in spec]
    if missing:
        raise UsageError(f"first approval of {name!r} needs --{' --'.join(missing)}")
    quote = text_arg(args.quote, "--quote", False)
    changed = bool(old_spec) and spec != old_spec
    if changed and not quote:
        raise UsageError(f"changing the spec of {name!r} ({spec_text(old_spec)} → {spec_text(spec)}) needs --quote "
                         "with the user's words")
    digest = sha256_file(path)
    store.state["deliverables"][name] = {"spec": spec, "current_sha256": digest, "path": store.relative(path)}
    text = f"approved deliverable {name} = {path.name} ({spec_text(spec)})"
    if changed:
        text += f"; spec changed {spec_text(old_spec)} → {spec_text(spec)}"
    store.decide(text, quote)
    store.save()
    print(f"Approved deliverable {name}: {store.relative(path)} sha256 {digest}")
    return 0


def parse_bbox(values):
    raw = values[0].split(",") if len(values) == 1 else values
    try:
        box = [int(str(v).strip()) for v in raw]
    except ValueError:
        raise UsageError("--bbox must be 4 integers: x0,y0,x1,y1") from None
    if len(box) != 4:
        raise UsageError("--bbox must be 4 integers: x0,y0,x1,y1")
    if box[0] < 0 or box[1] < 0 or box[2] <= box[0] or box[3] <= box[1]:
        raise UsageError("--bbox needs 0 <= x0 < x1 and 0 <= y0 < y1 (x1, y1 exclusive)")
    return box


def cmd_defect_add(args):
    store = open_store(args.project)
    item = store.deliverable(args.deliverable)
    spec = item.get("spec") or {}
    box = parse_bbox(args.bbox)
    if box[2] > spec.get("width", box[2]) or box[3] > spec.get("height", box[3]):
        raise UsageError(f"--bbox {box} is outside the deliverable size {spec.get('width')}x{spec.get('height')}")
    if args.master is not None and args.master not in store.state["masters"]:
        raise UsageError(f"unknown master {args.master!r}; run approve master first")
    if args.member is not None and spec.get("format") != "ZIP":
        raise UsageError("--member only applies to ZIP deliverables")
    note = text_arg(args.note, "--note")
    path = store.resolve(item.get("path", ""))
    if not path.is_file() or sha256_file(path) != item.get("current_sha256"):
        raise UsageError(f"{path} is missing or differs from the approved file; run approve deliverable for the file "
                         "the user is looking at, then add the defect")
    record = {"deliverable": args.deliverable, "bbox": box, "kind": args.kind, "source": args.source,
              "status": "open", "note": note, "reported_sha256": item["current_sha256"]}
    if args.master is not None:
        record["master"] = args.master
        record["master_sha256"] = store.state["masters"][args.master].get("sha256")
    if args.member is not None:
        record["member"] = text_arg(args.member, "--member")
    quote = text_arg(args.quote, "--quote", False)
    try:
        image = target_image(path, spec, record)
        record["region_hash"] = region_hash(image, box)
        reported = region_crop(image, box)
    except UsageError:
        raise
    except Exception as exc:
        raise UsageError(f"cannot read the defect region from {path.name}: {exc}") from None
    width, height = box[2] - box[0], box[3] - box[1]
    small = width < MIN_BOX or height < MIN_BOX or width * height < MIN_BOX_SHARE * image.size[0] * image.size[1]
    if small and not quote:
        raise UsageError(f"--bbox {width}x{height} is too small to prove a fix (needs >= {MIN_BOX}x{MIN_BOX} px and "
                         f">= {MIN_BOX_SHARE:.1%} of the image); draw a larger box or pass --quote with the user's words")
    if quote:
        record["quote"] = quote
    defects = store.defects()
    numbers = [int(m.group(1)) for m in (DEFECT_ID_RE.match(d["id"]) for d in defects) if m]
    record["id"] = f"D{max(numbers, default=0) + 1}"
    (store.root / "defects").mkdir(exist_ok=True)
    buffer = io.BytesIO()
    reported.save(buffer, "PNG")
    record["reported_crop"] = f"defects/{record['id']}-reported.png"
    atomic_write(store.root / record["reported_crop"], buffer.getvalue())
    record["history"] = [{"time": now(), "action": "add", "status": "open", "note": note}]
    defects.append(record)
    store.save_defects(defects)
    print(f"Added defect {record['id']}")
    return 0


def cmd_defect_close(args):
    store = open_store(args.project)
    note = text_arg(args.note, "--note")
    quote = text_arg(args.quote, "--quote", False)
    if args.status == "wontfix" and not quote:
        raise UsageError("--status wontfix needs --quote with the user's words accepting the defect")
    defects = store.defects()
    for item in defects:
        if item["id"] == args.id:
            item["status"] = args.status
            entry = {"time": now(), "action": "close", "status": args.status, "note": note}
            if quote:
                entry["quote"] = quote
            item.setdefault("history", []).append(entry)
            store.save_defects(defects)
            print(f"{args.id} -> {args.status}")
            return 0
    raise UsageError(f"unknown defect id {args.id!r}")


# ---------------------------------------------------------------- preferences

def pref_paths(brand):
    home = user_home()
    general = home / "preferences.md"
    return (home / "brands" / brand / "preferences.md" if brand else None), general


def read_prefs(path):
    if path is None:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return [(m.group(1), m.group(2)) for m in map(PREF_LINE.match, text.splitlines()) if m]


def cmd_pref_add(args):
    brand = ident(args.brand, "--brand") if args.brand is not None else None
    rule = text_arg(args.rule, "--rule")
    check = text_arg(args.check, "--check")
    evidence = text_arg(args.evidence, "--evidence", False)
    for label, value in (("--rule", rule), ("--check", check), ("--evidence", evidence)):
        if EMAIL_RE.search(value):
            raise UsageError(f"{label} looks like it contains an email address; preferences must not store accounts")
    path = pref_paths(brand)[0] if brand else pref_paths(None)[1]
    status = "confirmed" if args.confirmed else "proposed"
    entry = f"- [{status}] {rule} — check: {check}" + (f" — evidence: {evidence}" if evidence else "")
    try:
        text = path.read_text(encoding="utf-8") if path.is_file() else f"# Image Studio preferences: {brand or 'general'}\n\n"
    except (OSError, UnicodeDecodeError) as exc:
        raise UsageError(f"cannot read preferences at {path}: {exc}") from None
    lines = text.splitlines()
    prefix = re.compile(r"^- \[(confirmed|proposed)\] " + re.escape(rule) + " — check: ")
    hits = [i for i, line in enumerate(lines) if prefix.match(line)]
    if hits:
        old = prefix.match(lines[hits[0]]).group(1)
        if old == "confirmed" or old == status:
            raise UsageError(f"rule already recorded as {old} in {path}")
        lines[hits[0]] = entry
    else:
        lines.append(entry)
    new_text = "\n".join(lines) + "\n"
    if len(new_text) > PREF_CAP:
        raise UsageError(f"{path} would be {len(new_text)} characters (cap {PREF_CAP}); consolidate or remove "
                         "entries before adding more")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, new_text)
    except OSError as exc:
        raise UsageError(f"cannot write preferences at {path}: {exc}") from None
    print(f"{path}: {entry}")
    return 0


# ---------------------------------------------------------------- gate validity (shared by brief and the stop hook)

def gate_is_valid(store, name, defects):
    """A deliverable counts as gated only when its gate record points at a real run whose checklist hash is the
    current file and whose verdicts.json passes every defect; a record alone is never trusted."""
    item = store.state["deliverables"].get(name) or {}
    gate = store.state.get("gates", {}).get(name)
    if not isinstance(gate, dict) or not isinstance(gate.get("run_id"), str):
        return False
    if not re.match(r"^[A-Za-z0-9-]+$", gate["run_id"]):
        return False
    run_dir = store.root / "gate" / gate["run_id"]
    try:
        checklist = json.loads((run_dir / "checklist.json").read_text(encoding="utf-8"))
        verdicts = json.loads((run_dir / "verdicts.json").read_text(encoding="utf-8")) if (
            run_dir / "verdicts.json").is_file() else {}
        path = store.resolve(item.get("path", ""))
        current = sha256_file(path) if path.is_file() else None
    except (OSError, ValueError):
        return False
    if not isinstance(checklist, dict) or not isinstance(verdicts, dict):
        return False
    if checklist.get("deliverable") != name or not current:
        return False
    if not (current == item.get("current_sha256") == checklist.get("sha256") == gate.get("sha256")):
        return False
    if id_gaps(defects):
        return False
    entries = {e.get("id"): e for e in checklist.get("defects", []) if isinstance(e, dict)}
    mine = [d for d in defects if d.get("deliverable") == name]
    if any(d.get("status") == "open" for d in mine):
        return False
    if any(d.get("status") != "wontfix" and d["id"] not in entries for d in mine):
        return False
    needed = [d for d in mine if d.get("status") != "wontfix"]
    if needed and (verdicts.get("run_id") != checklist.get("run_id") or verdicts.get("nonce") != checklist.get("nonce")):
        return False
    given = verdicts.get("verdicts") if isinstance(verdicts.get("verdicts"), dict) else {}
    for defect in needed:
        verdict = given.get(defect["id"])
        hashes = {c.get("sha256") for c in (entries[defect["id"]].get("crops") or {}).values() if isinstance(c, dict)}
        if not isinstance(verdict, dict) or verdict.get("status") != "pass" or verdict.get("crop_sha256") not in hashes:
            return False
    return True


# ---------------------------------------------------------------- brief

def defect_line(d):
    extra = f" master {d['master']}" if d.get("master") else ""
    extra += f" member {d['member']}" if d.get("member") else ""
    box = ",".join(str(v) for v in d.get("bbox") or [])
    return (f"{d.get('id')} {d.get('status')} {d.get('deliverable')} [{d.get('kind')}] bbox {box}{extra} "
            f"({d.get('source')}): {short(d.get('note'))}")


def is_self_verified(run_dir):
    """Check if verdicts.json in run_dir has any verdict from reviewer 'self'."""
    if not run_dir:
        return False
    verdicts_path = Path(run_dir) / "verdicts.json"
    if not verdicts_path.is_file():
        return False
    try:
        vdata = json.loads(verdicts_path.read_text(encoding="utf-8"))
        vdict = vdata.get("verdicts") if isinstance(vdata, dict) and isinstance(vdata.get("verdicts"), dict) else {}
        return any(isinstance(v, dict) and v.get("reviewer") == "self" for v in vdict.values())
    except (OSError, ValueError):
        return False


def build_brief(store, max_lines):
    state = store.state
    defects = store.defects()
    current = plugin_version()
    seen = state.get("plugin_version_last_seen")
    head = [f"Brand: {state['brand']} | store: {store.root}"]
    head.append(f"Plugin version: {current or 'unknown'}")
    if current and seen != current:
        head.append(f"WARNING: plugin version changed from {seen} to {current} since this store was last used; "
                    "re-read the SKILL.md steps before working.")
        state["plugin_version_last_seen"] = current
        store.save()
    head.append("Precedence: latest user instruction > project decisions > brand prefs > general prefs.")
    for gap in id_gaps(defects):
        head.append(f"WARNING: {gap} missing from defects.jsonl (defects are never deleted, only closed)")
    open_items = [d for d in defects if d.get("status") == "open"]
    if open_items:
        head.append(f"Open defects ({len(open_items)}, all listed; gate cannot pass while any is open):")
        head += [f"- {defect_line(d)}" for d in open_items]
    else:
        head.append("Open defects: none")
    brand_file, general_file = pref_paths(state["brand"])
    prefs = read_prefs(brand_file) + read_prefs(general_file)
    proposed = sum(1 for status, _ in prefs if status == "proposed")
    if proposed:
        head.append(f"Preferences: {proposed} proposed, ask the user to confirm (pref add ... --confirmed).")

    sections = []
    deliverable_lines = []
    for name, item in sorted(state["deliverables"].items()):
        gate = state.get("gates", {}).get(name) or {}
        if gate_is_valid(store, name, defects):
            run_id = gate.get("run_id")
            run_dir = store.root / "gate" / run_id if run_id else None
            self_ver = is_self_verified(run_dir)
            passed = "gate passed (self-verified)" if self_ver else "gate passed run " + str(run_id)
        else:
            passed = "gate not passed for current file"
        deliverable_lines.append(f"- {name}: {spec_text(item.get('spec') or {})}, current {item.get('path')} sha256 "
                                 f"{str(item.get('current_sha256'))[:12]}, {passed}")
    sections.append(("Deliverables:", deliverable_lines))
    sections.append(("Masters (use only these):", [
        f"- {name} [{m.get('role')}] {m.get('path')} sha256 {str(m.get('sha256'))[:12]}"
        + (f": {short(m['note'])}" if m.get("note") else "") for name, m in sorted(state["masters"].items())]))
    sections.append(("Confirmed preferences:", [f"- {rule}" for status, rule in prefs if status == "confirmed"]))
    sections.append(("Recent decisions:", [f"- {d.get('time')} {short(d.get('text'))}" + (
        f' (user: "{short(d["quote"])}")' if d.get("quote") else "") for d in state["decisions"][-3:][::-1]]))
    closed = [d for d in defects if d.get("status") != "open"][::-1]
    sections.append(("Recently resolved defects (regression checks):", [f"- {defect_line(d)}" for d in closed]))

    lines = list(head)
    optional = sum(len(items) + 1 for _, items in sections if items)
    budget = max(0, max_lines - len(lines))
    if optional > budget:
        budget -= 1
    omitted = 0
    for title, items in sections:
        if not items:
            continue
        if budget >= 2:
            take = min(len(items), budget - 1)
            lines.append(title)
            lines += items[:take]
            budget -= take + 1
            omitted += len(items) - take
        else:
            omitted += len(items) + 1
    if omitted:
        lines.append(f"... {omitted} lines omitted (run brief --max-lines {max_lines + omitted})")
    return lines


def cmd_brief(args):
    if args.max_lines < 1:
        raise UsageError("--max-lines must be at least 1")
    store = open_store(args.project)
    print("\n".join(build_brief(store, args.max_lines)))
    return 0


# ---------------------------------------------------------------- logo check

def binary(img, cut=127):
    return img.point(lambda v: 255 if v > cut else 0)


def count_on(mask):
    return mask.histogram()[255]


def max_channel(diff):
    P = pil()
    r, g, b = diff.split()
    return P.ImageChops.lighter(P.ImageChops.lighter(r, g), b)


def color_distance(a, b):
    return max(abs(x - y) for x, y in zip(a, b))


def border_color(rgb):
    w, h = rgb.size
    strips = [rgb.crop((0, 0, w, 1)), rgb.crop((0, h - 1, w, h)), rgb.crop((0, 0, 1, h)), rgb.crop((w - 1, 0, w, h))]
    color = []
    for band in range(3):
        hist = [0] * 256
        for strip in strips:
            for i, n in enumerate(strip.getchannel(band).histogram()):
                hist[i] += n
        half, total = sum(hist) / 2.0, 0
        for value, count in enumerate(hist):
            total += count
            if total >= half:
                color.append(value)
                break
    return tuple(color)


def label(mask):
    """8-connected components of a 0/255 mask as lists of pixel indexes (pure Python, no numpy)."""
    w, h = mask.size
    data = mask.tobytes()
    seen = bytearray(w * h)
    comps = []
    start = data.find(b"\xff")
    while start != -1:
        if not seen[start]:
            seen[start] = 1
            stack, pixels = [start], []
            while stack:
                p = stack.pop()
                pixels.append(p)
                x, y = p % w, p // w
                for yy in (y - 1, y, y + 1):
                    if 0 <= yy < h:
                        row = yy * w
                        for xx in (x - 1, x, x + 1):
                            if 0 <= xx < w:
                                q = row + xx
                                if data[q] and not seen[q]:
                                    seen[q] = 1
                                    stack.append(q)
            comps.append(pixels)
        start = data.find(b"\xff", start + 1)
    return comps


def from_pixels(size, pixels):
    buf = bytearray(size[0] * size[1])
    for p in pixels:
        buf[p] = 255
    return pil().Image.frombytes("L", size, bytes(buf))


def palette_of(rgb, mask, limit=6):
    """Main stroke colours: coarse colour buckets covering >= 3% of the mask, returned as exact means."""
    P = pil()
    q = rgb.point(lambda v: (v >> 5) << 5)
    keyed = P.Image.composite(q, P.Image.new("RGB", rgb.size, (1, 1, 1)), mask)
    total = count_on(mask)
    buckets = sorted((c for c in keyed.getcolors(rgb.size[0] * rgb.size[1]) if c[1] != (1, 1, 1)), reverse=True)
    colors = []
    for n, color in buckets[:limit]:
        if n < 0.03 * total:
            break
        same = binary(max_channel(P.ImageChops.difference(q, P.Image.new("RGB", q.size, color))), 0)
        same = P.ImageChops.multiply(P.ImageChops.invert(same), mask)
        colors.append(tuple(int(round(v)) for v in P.ImageStat.Stat(rgb, same).mean))
    return colors


def master_model(master):
    """Tight stroke mask, colours and palette of the master (alpha strokes, or contrast to its border)."""
    P = pil()
    if has_alpha(master) and master.convert("RGBA").getchannel("A").getextrema()[0] < 255:
        mask = binary(master.convert("RGBA").getchannel("A"))
    else:
        rgb = master.convert("RGB")
        mask = binary(max_channel(P.ImageChops.difference(rgb, P.Image.new("RGB", rgb.size, border_color(rgb)))), 64)
    box = mask.getbbox()
    if box is None:
        return None
    rgb = master.convert("RGBA").convert("RGB").crop(box)
    mask = mask.crop(box)
    palette = palette_of(rgb, mask)
    for comp in label(mask):  # every component's own colour, however small (a tiny black star)
        if len(comp) >= SPECK:
            cm = from_pixels(mask.size, comp)
            core = cm.filter(P.ImageFilter.MinFilter(3))
            for color in palette_of(rgb, core if count_on(core) >= 4 else cm, limit=1):
                if all(color_distance(color, c) > STROKE_TOL // 2 for c in palette):
                    palette.append(color)
    return {"rgb": rgb, "mask": mask, "palette": palette}


def match_palette(rgb, palette):
    P = pil()
    out = P.Image.new("L", rgb.size, 0)
    for color in palette:
        d = max_channel(P.ImageChops.difference(rgb, P.Image.new("RGB", rgb.size, color)))
        out = P.ImageChops.lighter(out, d.point(lambda v: 255 if v <= STROKE_TOL else 0))
    return out


def flatten(img, palette):
    """RGB view; transparent pixels become a sentinel colour far from every stroke colour."""
    P = pil()
    if has_alpha(img):
        rgba = img.convert("RGBA")
        alpha = rgba.getchannel("A")
        if alpha.getextrema()[0] < 255:
            sentinel = max(SENTINELS, key=lambda s: min([color_distance(s, c) for c in palette] or [255]))
            return P.Image.composite(rgba.convert("RGB"), P.Image.new("RGB", img.size, sentinel), binary(alpha))
    return img.convert("RGB")


def overlap(a, b):
    """IoU with 1 px tolerance: share of each mask lying within 1 px of the other (antialiasing-safe)."""
    P = pil()
    na, nb = count_on(a), count_on(b)
    if not na or not nb:
        return 0.0
    da, db = a.filter(P.ImageFilter.MaxFilter(3)), b.filter(P.ImageFilter.MaxFilter(3))
    return (count_on(P.ImageChops.multiply(a, db)) + count_on(P.ImageChops.multiply(b, da))) / float(na + nb)


def fit(model, cand, box=None):
    """Scale the master to a box (default: the candidate's tight box): (score, master mask at that size, box)."""
    box = box or cand.getbbox()
    if box is None or box[2] <= box[0] or box[3] <= box[1]:
        return 0.0, None, None
    crop = cand.crop(box)
    master = binary(model["mask"].resize(crop.size, pil().BILINEAR))
    return overlap(master, crop), master, box


def placed_master(model, box):
    """Master mask and colours scaled to a candidate box."""
    P = pil()
    size = (box[2] - box[0], box[3] - box[1])
    return binary(model["mask"].resize(size, P.BILINEAR)), model["rgb"].resize(size, P.BILINEAR)


def agreement(region, model, box, mask=None):
    """Share of master stroke pixels (eroded core) whose colour on the candidate matches the master within tolerance.
    Background pixels outside the strokes do not count, so look-alike background colours cannot lower it."""
    P = pil()
    if box[2] - box[0] < 2 or box[3] - box[1] < 2:
        return 0.0
    master_mask, master_rgb = placed_master(model, box)
    core = mask if mask is not None else master_mask
    eroded = core.filter(P.ImageFilter.MinFilter(3))
    core = eroded if count_on(eroded) >= 4 else core
    total = count_on(core)
    if not total:
        return 0.0
    same = max_channel(P.ImageChops.difference(region.crop(box), master_rgb)).point(
        lambda v: 255 if v <= STROKE_TOL else 0)
    return count_on(P.ImageChops.multiply(same, core)) / float(total)


def refine(region, model, box):
    """Local search around a box (shift, then scale per axis) for the best colour agreement."""
    def moved(b, dx, dy, sx=1.0, sy=1.0):
        w, h = (b[2] - b[0]) * sx, (b[3] - b[1]) * sy
        cx, cy = (b[0] + b[2]) / 2.0 + dx, (b[1] + b[3]) / 2.0 + dy
        return (int(round(cx - w / 2)), int(round(cy - h / 2)), int(round(cx + w / 2)), int(round(cy + h / 2)))

    best, best_score = box, agreement(region, model, box)
    for step in (8, 4, 2, 1):
        trials = [moved(best, dx * step, dy * step) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
        trials += [moved(best, 0, 0, sx, sy) for sx in (0.95, 1.0, 1.05) for sy in (0.95, 1.0, 1.05)]
        for trial in trials:
            score = agreement(region, model, trial)
            if score > best_score + 1e-6:
                best, best_score = trial, score
    return best


def duplicate_share(region, raw, master_mask, box):
    """Stroke-coloured pixels outside the placed master that a shifted copy of the master explains
    (a logo pasted over an old one): (share of the logo area, best offset)."""
    P = pil()
    placed = P.Image.new("L", region.size, 0)
    placed.paste(master_mask.filter(P.ImageFilter.MaxFilter(5)), box[:2])
    extra_mask = P.ImageChops.subtract(raw, placed)
    extra = count_on(extra_mask)
    area = float(count_on(master_mask) or 1)
    if extra / area <= EXTRA_STROKES:
        return 0.0, None
    best, best_shift = 0, None
    for dx in range(-24, 25, 2):
        for dy in range(-24, 25, 2):
            if abs(dx) <= 2 and abs(dy) <= 2:
                continue
            shifted = P.Image.new("L", region.size, 0)
            shifted.paste(master_mask, (box[0] + dx, box[1] + dy))
            hit = count_on(P.ImageChops.multiply(extra_mask, shifted))
            if hit > best:
                best, best_shift = hit, (dx, dy)
    return best / area, best_shift


def candidate_boxes(model, region, raw):
    """Possible logo boxes: the tight box of all stroke-coloured pixels, and boxes predicted by anchoring the
    master's largest component on the three largest blobs of that component's own colour."""
    P = pil()
    boxes = []
    tight = raw.getbbox()
    if tight:
        boxes.append(tight)
    mw, mh = model["mask"].size
    mcomps = label(model["mask"])
    if not mcomps:
        return boxes
    biggest = max(mcomps, key=len)
    anchor_mask = from_pixels(model["mask"].size, biggest)
    anchor = anchor_mask.getbbox()
    anchor_color = tuple(masked_stats(model["rgb"], anchor_mask)[0])
    aw, ah = anchor[2] - anchor[0], anchor[3] - anchor[1]
    for source in (match_palette(region, [anchor_color]), raw):
        for comp in sorted(label(source), key=len, reverse=True)[:3]:
            cb = from_pixels(raw.size, comp).getbbox()
            sx, sy = (cb[2] - cb[0]) / float(aw), (cb[3] - cb[1]) / float(ah)
            if not 0.8 < sx / sy < 1.25:
                continue
            x0, y0 = cb[0] - anchor[0] * sx, cb[1] - anchor[1] * sy
            predicted = (int(round(x0)), int(round(y0)), int(round(x0 + mw * sx)), int(round(y0 + mh * sy)))
            boxes.append(predicted)
            clip = P.Image.new("L", raw.size, 0)
            clip.paste(255, (predicted[0] - 2, predicted[1] - 2, predicted[2] + 2, predicted[3] + 2))
            clipped = P.ImageChops.multiply(raw, clip).getbbox()
            if clipped:
                boxes.append(clipped)
    return boxes


def masked_stats(rgb, mask):
    if not count_on(mask):
        return None
    stat = pil().ImageStat.Stat(rgb, mask)
    return [int(round(v)) for v in stat.mean], sum(stat.stddev) / 3.0


def colour_bins(rgb, mask):
    P = pil()
    q = rgb.point(lambda v: v >> 5)
    keyed = P.Image.composite(q, P.Image.new("RGB", rgb.size, (255, 255, 255)), mask)
    total = float(count_on(mask)) or 1.0
    return {c: n / total for n, c in keyed.getcolors(rgb.size[0] * rgb.size[1]) if c != (255, 255, 255)}


def near_share(color, ref):
    r, g, b = color
    return max(ref.get((r + i, g + j, b + k), 0.0) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1))


def foreign_share(inner, ref, factor=3.0):
    """Share of `inner` pixels in colour bins over-represented versus `ref` (neighbour bins count as present)."""
    return sum(max(0.0, f - factor * near_share(color, ref)) for color, f in inner.items())


def logo_check(store, defect, img, threshold):
    """Compare the logo inside the defect bbox with its master.

    Returns (status, text) with status pass, fail, or inconclusive.
    Hard checks on every background: each master component present with its colour (colour agreement on the
    stroke pixels) and the aspect ratio. Colour-sensitive checks (IoU of stroke-coloured pixels, flat patch,
    leftover colours) fail on plain backgrounds; on a busy background (one that shares the logo colours or varies
    a lot) they are reported as inconclusive and the gate then requires an independent verdict.
    """
    did = defect["id"]
    info = store.state["masters"].get(defect.get("master"))
    if not isinstance(info, dict):
        return "fail", f"{did} logo: master {defect.get('master')!r} is not in the store"
    master_path = store.root / info.get("path", "")
    try:
        model = master_model(open_image(master_path))
    except UsageError:
        raise
    except Exception as exc:
        return "fail", f"{did} logo: cannot read master ({exc})"
    if model is None:
        return "fail", f"{did} logo: master has no visible strokes"
    P = pil()
    W, H = img.size
    x0, y0, x1, y1 = defect["bbox"]
    x1, y1 = min(x1, W), min(y1, H)
    if x1 <= x0 or y1 <= y0:
        return "fail", f"{did} logo: bbox is outside the image"
    outer = (max(0, x0 - BAND), max(0, y0 - BAND), min(W, x1 + BAND), min(H, y1 + BAND))
    around = flatten(img.crop(outer), model["palette"])
    inner_box = (x0 - outer[0], y0 - outer[1], x1 - outer[0], y1 - outer[1])
    scale = LOGO_MAX_SIDE / float(max(around.size))
    if scale < 1:  # keep the pure-Python component labelling fast on large logos
        around = around.resize((max(1, round(around.size[0] * scale)), max(1, round(around.size[1] * scale))),
                               P.BILINEAR)
        inner_box = tuple(int(round(v * scale)) for v in inner_box)
    region = around.crop(inner_box)
    raw = match_palette(region, model["palette"])
    head = f"{did} logo vs master {defect['master']}"

    # Background: busy when it shares the logo colours or its two halves differ.
    band = P.Image.new("L", around.size, 255)
    band.paste(0, inner_box)
    band_match = count_on(P.ImageChops.multiply(match_palette(around, model["palette"]), band))
    lookalike = band_match / float(count_on(band) or 1)
    ow, oh = around.size
    top_half = P.Image.new("L", around.size, 0)
    top_half.paste(255, (0, 0, ow, oh // 2))
    bins_a = colour_bins(around, P.ImageChops.multiply(band, top_half))
    bins_b = colour_bins(around, P.ImageChops.subtract(band, top_half))
    baseline = max(foreign_share(bins_a, bins_b), foreign_share(bins_b, bins_a)) if bins_a and bins_b else 0.0
    busy = baseline > BUSY_BASELINE or lookalike > LOOKALIKE_SHARE

    boxes = candidate_boxes(model, region, raw)
    if not boxes:
        return "fail", f"{head}: IoU 0.00 (min {threshold:.2f}), no strokes of the master colours inside the bbox"
    ranked = sorted(set(boxes), key=lambda b: agreement(region, model, b), reverse=True)[:3]
    box = max((refine(region, model, b) for b in ranked), key=lambda b: (round(agreement(region, model, b), 3),
                                                                          fit(model, raw, b)[0]))
    agree = agreement(region, model, box)
    score, master, _ = fit(model, raw, box)
    master_mask, master_rgb = placed_master(model, box)
    size_ratio = master_mask.size[0] / float(model["mask"].size[0])
    speck = max(2.0, SPECK * size_ratio * size_ratio)
    want = [c for c in label(master_mask) if len(c) >= speck]
    hard, soft = [], []
    got = 0
    cand_rgb = region.crop(box)
    for n, comp in enumerate(sorted(want, key=lambda c: c[0]), 1):
        cm = from_pixels(master_mask.size, comp)
        share = agreement(region, model, box, cm)
        core = cm.filter(P.ImageFilter.MinFilter(3))
        cm = core if count_on(core) >= 4 else cm
        want_c, got_c = masked_stats(master_rgb, cm)[0], masked_stats(cand_rgb, cm)[0]
        if share >= 0.6:
            got += 1
        else:
            hard.append(f"component {n} missing ({share:.0%} of its pixels match)")
        if color_distance(want_c, got_c) > STROKE_TOL:
            hard.append(f"component {n} colour {tuple(got_c)} vs master {tuple(want_c)}")
    aspect = (master_mask.size[0] / float(master_mask.size[1])) / (model["mask"].size[0] / float(model["mask"].size[1]))
    if abs(aspect - 1) > ASPECT_TOL:
        hard.append(f"aspect ratio off by {abs(aspect - 1):.0%} (max {ASPECT_TOL:.0%})")
    if score < threshold:
        soft.append(f"IoU below {threshold:.2f}")
    extra, shift = duplicate_share(region, raw, master_mask, box)
    if extra > EXTRA_STROKES:
        soft.append(f"a second copy of the logo shows at offset {shift} ({extra:.0%} of the logo area): duplicate "
                    "or leftover logo")

    # What surrounds the strokes inside the bbox must look like the band just outside it.
    inner_mask = P.ImageChops.invert(raw.filter(P.ImageFilter.MaxFilter(5)))
    in_bins, band_bins = colour_bins(region, inner_mask), colour_bins(around, band)
    in_stats, band_stats = masked_stats(region, inner_mask), masked_stats(around, band)
    inner_std = in_stats[1] if in_stats else 0.0
    band_std = band_stats[1] if band_stats else 0.0
    foreign = 0.0
    if in_bins and band_bins:
        top_color, top = max(in_bins.items(), key=lambda kv: kv[1])
        if top > 0.30 and near_share(top_color, band_bins) < 0.02:
            soft.append(f"flat patch: {top:.0%} of the bbox background is a colour not found around it")
        elif inner_std < 4 and band_std > 15:
            soft.append(f"flat patch: the bbox background is flat (std {inner_std:.1f}) but its surroundings "
                        f"are not (std {band_std:.1f})")
        foreign = foreign_share(in_bins, band_bins)
        if foreign > baseline + 0.03:
            soft.append(f"{foreign:.0%} of the bbox background has colours not found around it "
                        "(leftover logo, stain, or patch?)")
    numbers = (f"{head}: IoU {score:.2f} (min {threshold:.2f}), components master {len(want)} / candidate {got}, "
               f"colour match {agree:.0%}, extra {extra:.0%}, aspect {aspect:.2f}, background foreign {foreign:.0%} "
               f"(baseline {baseline:.0%}, logo-coloured {lookalike:.0%})")
    if hard or (soft and not busy):
        return "fail", numbers + "; " + "; ".join(hard + soft)
    if busy:
        detail = ("; " + "; ".join(soft)) if soft else ""
        return "inconclusive", (numbers + detail + "; logo check inconclusive (busy background): colour-based checks "
                                "are not reliable here, so this defect needs a verdict with --reviewer independent")
    return "pass", numbers


# ---------------------------------------------------------------- gate

class Report:
    def __init__(self):
        self.checked, self.not_checked, self.failing = [], [], []

    def ok(self, text):
        self.checked.append(text)

    def skip(self, text):
        self.not_checked.append(text)

    def fail(self, text):
        self.failing.append(text)

    def passed(self):
        return not self.failing and not self.not_checked

    def lines(self):
        out = []
        for title, items in (("Checked", self.checked), ("Not checked", self.not_checked),
                             ("Still failing", self.failing)):
            out.append(f"{title}:")
            out += [f"- {item}" for item in items] or ["- (none)"]
        return out


def spec_checks(path, spec, report):
    fmt = spec.get("format")
    if fmt == "ZIP":
        if not zipfile.is_zipfile(path):
            report.fail(f"format: {path.name} is not a ZIP archive (spec ZIP)")
            return
        try:
            with zipfile.ZipFile(path) as archive:
                members = [i for i in archive.infolist() if not i.is_dir()]
            names = [i.filename for i in members]
            images, problems = zip_images(path)
        except (zipfile.BadZipFile, OSError) as exc:
            report.fail(f"format: cannot read ZIP {path.name} ({exc})")
            return
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            report.fail(f"ZIP has duplicate member names: {', '.join(dupes[:5])}")
        leaked = memory_paths(names)
        for nested in [i for i in members if i.filename.lower().endswith(".zip")]:
            try:
                with zipfile.ZipFile(path) as archive, zipfile.ZipFile(io.BytesIO(archive.read(nested))) as inner:
                    leaked += [f"{nested.filename}!{n}" for n in memory_paths(
                        [i.filename for i in inner.infolist() if not i.is_dir()])]
            except (zipfile.BadZipFile, OSError, ValueError) as exc:
                report.fail(f"{nested.filename}: cannot read nested ZIP ({exc})")
        if leaked:
            report.fail(f"ZIP contains project memory ({STORE_DIR}/ must never ship): {', '.join(leaked[:5])}")
        else:
            report.ok(f"ZIP has no {STORE_DIR}/ paths")
        for problem in problems:
            report.fail(problem)
        if not images:
            report.fail("ZIP contains no images")
        bad = 0
        with zipfile.ZipFile(path) as archive:
            infos = [i for i in archive.infolist() if not i.is_dir() and i.filename in images]
        for info in infos:
            issues = image_problems(open_image(path, info), spec, info.filename)
            bad += bool(issues)
            for issue in issues:
                report.fail(issue)
        if infos and not bad:
            report.ok(f"all {len(infos)} images in the ZIP are {spec['width']}x{spec['height']}, alpha {spec['alpha']}")
        return
    try:
        img = open_image(path)
    except UsageError:
        raise
    except Exception as exc:
        report.fail(f"format: cannot open {path.name} as an image ({exc})")
        return
    if img.format != fmt:
        report.fail(f"format: {path.name} is {img.format}, spec {fmt}")
    problems = image_problems(img, spec, path.name)
    for problem in problems:
        report.fail(problem)
    if img.format == fmt and not problems:
        report.ok(f"spec: {spec['width']}x{spec['height']} {fmt}, alpha {spec['alpha']}")


def render_crops(image, defect_id, crop_box, nonce):
    """PNG bytes of the 100% and 200% crops; deterministic for a given image, box and nonce."""
    P = pil()
    crop = image.crop(tuple(crop_box))
    crop = crop.convert("RGBA" if has_alpha(crop) else "RGB")
    info = P.PngImagePlugin.PngInfo()
    info.add_text("image-studio-run", nonce)  # makes every run's crop hash unique
    out = {}
    for scale, img in (("100", crop), ("200", crop.resize((crop.size[0] * 2, crop.size[1] * 2), P.NEAREST))):
        buffer = io.BytesIO()
        img.save(buffer, "PNG", pnginfo=info)
        out[scale] = (f"{defect_id}-{scale}.png", buffer.getvalue())
    return out


def crop_box_for(image, bbox):
    x0, y0, x1, y1 = bbox
    w, h = image.size
    return [max(0, x0 - CROP_MARGIN), max(0, y0 - CROP_MARGIN), min(w, x1 + CROP_MARGIN), min(h, y1 + CROP_MARGIN)]


def new_run(store, name, path, digest, spec, defects, threshold):
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    run_dir = store.root / "gate" / run_id
    run_dir.mkdir(parents=True)
    nonce = secrets.token_hex(16)
    entries = []
    for defect in defects:
        entry = {"id": defect["id"], "status": defect.get("status"), "kind": defect.get("kind"), "bbox": defect["bbox"],
                 "crops": {}}
        if defect.get("member"):
            entry["member"] = defect["member"]
        try:
            image = target_image(path, spec, defect)
            entry["crop_box"] = crop_box_for(image, defect["bbox"])
            if entry["crop_box"][2] <= entry["crop_box"][0] or entry["crop_box"][3] <= entry["crop_box"][1]:
                entry["error"] = "bbox is outside the image"
            else:
                for scale, (file_name, data) in render_crops(image, defect["id"], entry["crop_box"], nonce).items():
                    atomic_write(run_dir / file_name, data)
                    entry["crops"][scale] = {"file": file_name, "sha256": sha256_bytes(data)}
        except UsageError:
            raise
        except Exception as exc:
            entry["crop_box"], entry["error"] = None, f"cannot crop ({exc})"
        entries.append(entry)
    checklist = {"run_id": run_id, "nonce": nonce, "deliverable": name, "file": str(path), "sha256": digest,
                 "created": now(), "iou_threshold": threshold, "defects": entries}
    atomic_write(run_dir / "checklist.json", dump_json(checklist))
    return run_id, run_dir, checklist


def load_run(store, run_id):
    if not isinstance(run_id, str) or not re.match(r"^[A-Za-z0-9-]+$", run_id):
        raise UsageError(f"bad run id {run_id!r}")
    run_dir = store.root / "gate" / run_id
    if not (run_dir / "checklist.json").is_file():
        raise UsageError(f"unknown gate run {run_id!r} (no {run_dir / 'checklist.json'})")
    return run_dir, read_json(run_dir / "checklist.json", "checklist.json")


def check_run_integrity(store, run_id, run_dir, checklist, path, digest, item, spec, report):
    """--run mode: the run must still describe the approved current file, byte for byte."""
    if checklist.get("sha256") != digest or checklist.get("sha256") != item.get("current_sha256"):
        report.fail(f"run {run_id} is stale: it was made for sha256 {str(checklist.get('sha256'))[:12]}, the file is "
                    f"{digest[:12]} and the approved current is {str(item.get('current_sha256'))[:12]}; start a new "
                    "gate run")
    nonce = str(checklist.get("nonce", ""))
    for entry in checklist.get("defects", []):
        if not isinstance(entry, dict):
            report.fail(f"run {run_id} is stale: checklist.json has a malformed entry; start a new gate run")
            continue
        crops = entry.get("crops") or {}
        for crop in crops.values():
            crop_path = run_dir / str(crop.get("file", ""))
            if not crop_path.is_file() or sha256_file(crop_path) != crop.get("sha256"):
                report.fail(f"{entry.get('id')}: crop {crop.get('file')} was changed or removed after the run; "
                            "start a new gate run")
        if not crops or not entry.get("crop_box"):
            continue
        try:
            image = target_image(path, spec, entry)
            fresh = render_crops(image, entry["id"], entry["crop_box"], nonce)
        except UsageError:
            raise
        except Exception:
            fresh = {}
        if any(sha256_bytes(fresh.get(scale, ("", b""))[1]) != crop.get("sha256") for scale, crop in crops.items()):
            report.fail(f"run {run_id} is stale: the crops of {entry.get('id')} no longer match the file; start a new "
                        "gate run")


def check_verdicts(run_dir, checklist, defects, report, need_independent):
    """Check verdicts.json of this run; return the defect ids that still need a (new) verdict."""
    pending = []
    by_id = {e["id"]: e for e in checklist.get("defects", []) if isinstance(e, dict) and "id" in e}
    path = run_dir / "verdicts.json"
    verdicts, problem = {}, None
    if path.is_file():
        try:
            data = read_json(path, "verdicts.json")
        except UsageError as exc:
            data, problem = None, str(exc)
        if data is not None:
            if data.get("run_id") != checklist["run_id"] or data.get("nonce") != checklist["nonce"]:
                problem = "verdicts.json belongs to another run (run_id/nonce mismatch); verdicts must be made for this run"
            elif not isinstance(data.get("verdicts"), dict):
                problem = "verdicts.json has no verdicts object"
            else:
                verdicts = data["verdicts"]
    if problem:
        report.fail(problem)
    for defect in defects:
        did = defect["id"]
        entry = by_id.get(did)
        if defect.get("status") == "wontfix":
            closing = next((h for h in reversed(defect.get("history") or []) if isinstance(h, dict)
                            and h.get("status") == "wontfix"), {})
            quote = closing.get("quote")
            if quote:
                report.ok(f"{did} accepted by user (wontfix): {short(quote)}")
            else:
                report.fail(f"{did} is wontfix without the user's words; close it again with --quote")
            continue
        if entry is None:
            report.fail(f"{did} is not in run {checklist['run_id']} (added later); start a new gate run")
            continue
        if entry.get("error") or not entry.get("crops"):
            report.fail(f"{did}: {entry.get('error') or 'no crops'}")
            continue
        verdict = verdicts.get(did)
        crop_names = " and ".join(c["file"] for c in entry["crops"].values())
        reviewer_ok = isinstance(verdict, dict) and (did not in need_independent
                                                     or verdict.get("reviewer") == "independent")
        if not isinstance(verdict, dict) or verdict.get("status") != "pass" or not reviewer_ok:
            pending.append((did, entry["crops"]["100"]["file"]))
        if not isinstance(verdict, dict):
            report.skip(f"{did}: no verdict yet; inspect {crop_names} in {run_dir}")
            continue
        hashes = {c["sha256"] for c in entry["crops"].values()}
        evidence = verdict.get("evidence")
        if verdict.get("crop_sha256") not in hashes:
            report.fail(f"{did}: verdict rejected, crop_sha256 does not match any crop of this run")
        elif not isinstance(evidence, str) or len(evidence.strip()) < MIN_EVIDENCE:
            report.fail(f"{did}: verdict rejected, evidence must describe what was seen (>= {MIN_EVIDENCE} chars)")
        elif verdict.get("reviewer") not in ("self", "independent"):
            report.fail(f"{did}: verdict rejected, reviewer must be self or independent")
        elif not reviewer_ok:
            report.fail(f"{did}: the logo check was inconclusive, so it needs a verdict with --reviewer independent")
        elif verdict.get("status") == "pass":
            report.ok(f"{did} pass ({verdict['reviewer']}): {short(evidence.strip())}")
        elif verdict.get("status") == "fail":
            report.fail(f"{did} verdict fail: {short(evidence.strip())}")
        elif verdict.get("status") == "uncertain":
            report.skip(f"{did} verdict uncertain: {short(evidence.strip())}")
        else:
            report.fail(f"{did}: verdict rejected, status must be pass, fail or uncertain")
    return pending


def resolved_proof(store_root, path, spec, digest, defects, report):
    """A resolved defect must show a change: the file and the pixels in its bbox differ from when it was reported."""
    for defect in defects:
        if defect.get("status") != "resolved":
            continue
        did = defect["id"]
        if defect.get("reported_sha256") and defect["reported_sha256"] == digest:
            report.fail(f"{did} marked resolved but the deliverable file is unchanged since it was reported")
            continue
        try:
            current = region_crop(target_image(path, spec, defect), defect["bbox"])
            same = bool(defect.get("region_hash")) and region_hash(current, [0, 0] + list(current.size)) == defect[
                "region_hash"]
            share = None
            if not same and defect.get("reported_crop"):
                share = changed_share(open_image(store_root / defect["reported_crop"]), current)
        except UsageError:
            raise
        except Exception as exc:
            report.fail(f"{did}: cannot read its region to confirm the fix ({exc})")
            continue
        if same:
            report.fail(f"{did} marked resolved but its pixels are unchanged since it was reported")
        elif share is not None and share < MIN_CHANGED:
            report.fail(f"{did} marked resolved but almost nothing changed in its box ({share:.1%} of pixels)")


def id_gaps(defects):
    """Defect ids missing between D1 and the highest id (defects are never deleted, only closed)."""
    numbers = {int(m.group(1)) for m in (DEFECT_ID_RE.match(str(d.get("id"))) for d in defects) if m}
    return [f"D{n}" for n in range(1, max(numbers, default=0)) if n not in numbers]


def disappeared(store, name, defects):
    """Defect ids recorded in earlier runs of this deliverable that are gone from defects.jsonl."""
    known = {d["id"] for d in defects}
    gone = set()
    for checklist_path in sorted((store.root / "gate").glob("*/checklist.json")):
        try:
            checklist = json.loads(checklist_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(checklist, dict) and checklist.get("deliverable") == name:
            gone |= {e.get("id") for e in checklist.get("defects", []) if isinstance(e, dict)} - known
    return sorted(g for g in gone if isinstance(g, str))


def master_problem(store, defect, report):
    """The master a logo defect is checked against must be the approved file; a replacement counts only with the
    user's quote (reported under Checked, and the new master is used)."""
    did, name = defect["id"], defect.get("master")
    info = store.state["masters"].get(name)
    if not isinstance(info, dict):
        return f"{did} logo: master {name!r} is not in the store"
    try:
        actual = sha256_file(store.root / info.get("path", ""))
    except OSError:
        return f"{did} logo: master file for {name!r} is missing"
    if actual != info.get("sha256"):
        return f"{did} logo: master file {info.get('path')} changed since approval"
    recorded = defect.get("master_sha256")
    if recorded and recorded != info.get("sha256"):
        quotes = [r.get("quote") for r in info.get("replaced") or [] if isinstance(r, dict)
                  and r.get("sha256") == info.get("sha256") and r.get("quote")]
        if not quotes:
            return f"{did} logo: master {name!r} differs from the one recorded with the defect and has no user quote"
        report.ok(f"{did} master replaced by user: {short(quotes[-1])}")
    return None


def cmd_gate(args):
    if not DEFAULT_IOU <= args.iou_threshold <= 1:
        raise UsageError(f"--iou-threshold can only raise the floor: use a value from {DEFAULT_IOU:.2f} to 1")
    store = open_store(args.project)
    name = args.deliverable
    item = store.deliverable(name)
    spec = item.get("spec") or {}
    path = Path(args.file).expanduser() if args.file else store.resolve(item.get("path", ""))
    if not path.is_file():
        raise UsageError(f"deliverable file {path} does not exist")
    digest = sha256_file(path)
    report = Report()
    if digest != item.get("current_sha256"):
        report.fail(f"{path.name} is not the approved current file — run approve deliverable "
                    f"(file sha256 {digest[:12]}, approved {str(item.get('current_sha256'))[:12]})")
    else:
        report.ok(f"{path.name} is the approved current file (sha256 {digest[:12]})")
    spec_checks(path, spec, report)

    all_defects = store.defects()
    defects = [d for d in all_defects if d.get("deliverable") == name]
    for gone in disappeared(store, name, all_defects):
        report.fail(f"defect {gone} disappeared from defects.jsonl")
    for gap in id_gaps(all_defects):
        report.fail(f"{gap} missing from defects.jsonl (defects are never deleted, only closed)")
    threshold = args.iou_threshold
    if args.run:
        run_dir, checklist = load_run(store, args.run)
        if checklist.get("deliverable") != name:
            raise UsageError(f"run {args.run} is for deliverable {checklist.get('deliverable')!r}, not {name!r}")
        run_id = args.run
        recorded = checklist.get("iou_threshold")
        if isinstance(recorded, (int, float)) and not isinstance(recorded, bool):
            threshold = max(threshold, float(recorded))
        check_run_integrity(store, run_id, run_dir, checklist, path, digest, item, spec, report)
    else:
        run_id, run_dir, checklist = new_run(store, name, path, digest, spec, defects, threshold)
    stale = any("is stale" in f or "not the approved current file" in f or "after the run" in f
                for f in report.failing)
    resolved_proof(store.root, path, spec, digest, defects, report)

    need_independent = set()
    for defect in defects:
        if defect.get("kind") != "logo" or defect.get("status") == "wontfix":
            continue
        if not defect.get("master"):
            report.ok(f"{defect['id']} logo check skipped (no master); manual verdict governs")
            continue
        problem = master_problem(store, defect, report)
        if problem:
            report.fail(problem)
            continue
        try:
            status, text = logo_check(store, defect, target_image(path, spec, defect), threshold)
        except UsageError:
            raise
        except Exception as exc:
            status, text = "fail", f"{defect['id']} logo: cannot check ({exc})"
        if status == "pass":
            report.ok(text)
        elif status == "inconclusive":
            report.ok("WARNING " + text)
            need_independent.add(defect["id"])
        else:
            report.fail(text)

    pending = check_verdicts(run_dir, checklist, defects, report, need_independent)
    for defect in defects:
        if defect.get("status") == "open":
            report.fail(f"{defect['id']} is still open: {short(defect.get('note'))}")

    passed = report.passed()
    print(f"Gate: {name} ({store.relative(path)})")
    print(f"Run: {run_id} (crops and checklist in {run_dir})")
    print("\n".join(report.lines()))
    self_verified = is_self_verified(run_dir)
    if passed:
        gate_rec = {"deliverable": name, "sha256": digest, "run_id": run_id,
                    "time": now(), "iou_threshold": threshold}
        if self_verified:
            gate_rec["self_verified"] = True
        store.state.setdefault("gates", {})[name] = gate_rec
        store.save()

        result_label = "Result: PASS (self-verified — not independently reviewed)" if self_verified else "Result: PASS"
        try:
            print(result_label)
        except UnicodeEncodeError:
            print("Result: PASS (self-verified - not independently reviewed)")
    else:
        print("Result: FAIL")
        print("Next:")
        for line in next_steps(name, path, digest, item, defects, run_id, stale, pending, need_independent):
            print(f"- {line}")
    return 0 if passed else 1


def next_steps(name, path, digest, item, defects, run_id, stale, pending, need_independent):
    """Exact commands the agent must run before this gate can pass."""
    steps = []
    if digest != item.get("current_sha256"):
        steps.append(f"if {path.name} is the file the user should receive: {SCRIPT_HINT} approve deliverable "
                     f"--name {name} --file {shlex.quote(str(path))}; otherwise gate the approved file")
    for defect in defects:
        if defect.get("status") == "open":
            steps.append(f"fix {defect['id']} ({short(defect.get('note'))}), check it, then {SCRIPT_HINT} defect "
                         f"close --id {defect['id']} --status resolved --note \"what changed\" (or, only if the user "
                         "accepts it: --status wontfix --quote \"the user's words\")")
    if stale:
        steps.append(f"start a new run after the steps above: {SCRIPT_HINT} gate --deliverable {name}")
        return steps
    for did, crop in pending:
        reviewer = " --reviewer independent (a reviewer other than you)" if did in need_independent else ""
        steps.append(f"open {crop} (and the 200% crop) of run {run_id}, then {SCRIPT_HINT} verdict --run {run_id} "
                     f"--id {did} --status pass|fail|uncertain --evidence \"what you saw\"{reviewer}")
    steps.append(f"then: {SCRIPT_HINT} gate --deliverable {name} --run {run_id} (spec, logo, or unchanged-pixel "
                 "failures need a fixed file, a new approve deliverable, and a new run)")
    return steps


def cmd_verdict(args):
    store = open_store(args.project)
    run_dir, checklist = load_run(store, args.run)
    entry = next((e for e in checklist.get("defects", []) if isinstance(e, dict) and e.get("id") == args.id), None)
    if entry is None:
        raise UsageError(f"defect {args.id!r} is not in run {args.run}")
    crop = (entry.get("crops") or {}).get(args.crop)
    if not crop:
        raise UsageError(f"run {args.run} has no {args.crop}% crop for {args.id}")
    crop_path = run_dir / crop["file"]
    if not crop_path.is_file() or sha256_file(crop_path) != crop["sha256"]:
        raise UsageError(f"{crop_path} is missing or changed since the run; start a new gate run")
    evidence = text_arg(args.evidence, "--evidence")
    if len(evidence) < MIN_EVIDENCE:
        raise UsageError(f"--evidence must describe what you saw in the crop (>= {MIN_EVIDENCE} characters)")
    path = run_dir / "verdicts.json"
    data = {}
    if path.is_file():
        try:
            data = read_json(path, "verdicts.json")
        except UsageError:
            data = {}
    if data.get("run_id") != checklist["run_id"] or data.get("nonce") != checklist["nonce"]:
        data = {}
    data.update({"run_id": checklist["run_id"], "nonce": checklist["nonce"], "deliverable": checklist.get("deliverable")})
    data.setdefault("verdicts", {})[args.id] = {"status": args.status, "crop_sha256": crop["sha256"],
                                                "evidence": evidence, "reviewer": args.reviewer, "time": now()}
    atomic_write(path, dump_json(data))
    print(f"{args.id} {args.status} recorded in {path}")
    return 0


# ---------------------------------------------------------------- hooks

def last_message_from_transcript(path):
    with open(path, "rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - (2 << 20)))
        lines = handle.read().decode("utf-8", "replace").splitlines()
    for line in reversed(lines):
        if len(line) > (1 << 20):
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        for candidate in (entry, entry.get("message"), entry.get("payload")):
            if not isinstance(candidate, dict):
                continue
            if candidate.get("role") != "assistant" and entry.get("type") != "assistant":
                continue
            content = candidate.get("content")
            if isinstance(content, str) and content.strip():
                return content
            if isinstance(content, list):
                text = "\n".join(c["text"] for c in content if isinstance(c, dict) and isinstance(c.get("text"), str))
                if text.strip():
                    return text
    return ""


def allowed_final_message(text, required_still_failing=None, store=None):
    """While a gate is missing, the only acceptable final messages are an honest status report (all three headings
    Checked / Not checked / Still failing, or Đã kiểm / Chưa kiểm / Còn lỗi with content, naming open defects and
    ungated deliverables) or a question to the user (the last non-empty line ends with "?" or "？" without completion words)."""
    text = unicodedata.normalize("NFC", text or "").strip()
    if not text:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and lines[-1].endswith(("?", "？")):
        if not COMPLETION_RE.search(text):
            return True

    matches = [heading.search(text) for heading in REPORT_HEADINGS]
    if not all(matches):
        return False

    indexed = sorted(enumerate(matches), key=lambda item: item[1].start())
    for i in range(len(indexed) - 1):
        if indexed[i][1].end() > indexed[i + 1][1].start():
            return False

    contents = {}
    for i in range(len(indexed)):
        cat, m = indexed[i]
        start_pos = m.end()
        end_pos = indexed[i + 1][1].start() if i + 1 < len(indexed) else len(text)
        content = text[start_pos:end_pos]
        if not re.sub(r"[\s#*>_|:\-]+", "", content):
            return False
        contents[cat] = content

    if store is not None:
        try:
            req = set(d.get("id") for d in store.defects() if isinstance(d, dict) and d.get("status") == "open")
            req |= set(ungated(store))
        except Exception:
            req = set()
        if required_still_failing is not None:
            req |= set(required_still_failing)
        required_still_failing = req
    elif required_still_failing is None:
        required_still_failing = ()

    still_failing_text = contents.get(2, "")
    for item in required_still_failing:
        if not item:
            continue
        pat = rf"(?<![A-Za-z0-9_]){re.escape(str(item))}(?![A-Za-z0-9_])"
        if not re.search(pat, still_failing_text, re.IGNORECASE):
            return False

    return True


def store_fingerprint(store):
    """Changes whenever defects, deliverable hashes, or gate records change (so a stale block marker expires)."""
    try:
        defects = store.defects_path.read_bytes()
    except OSError:
        defects = b""
    current = sorted((name, str(item.get("current_sha256"))) for name, item in store.state["deliverables"].items()
                     if isinstance(item, dict))
    return sha256_bytes(defects + json.dumps([current, store.state.get("gates")], sort_keys=True,
                                             default=str).encode("utf-8"))


def ungated(store):
    """Deliverables without a valid passing gate for their current file."""
    defects = store.defects()
    return [name for name in sorted(store.state["deliverables"]) if not gate_is_valid(store, name, defects)]


def block_once(root, payload, message, fingerprint, reason):
    key = sha256_bytes("\0".join((str(payload.get("session_id") or ""), str(payload.get("turn_id") or ""),
                                   unicodedata.normalize("NFC", message), fingerprint)).encode("utf-8"))
    marker_path = root / "stop-hook.json"
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        marker = {}
    if isinstance(marker, dict) and marker.get("key") == key:
        return ""  # this exact message was already blocked for this store state
    try:
        atomic_write(marker_path, dump_json({"key": key, "time": now()}))
    except OSError:
        pass  # read-only store: still block; stop_hook_active keeps it loop-safe
    return json.dumps({"decision": "block", "reason": reason})


def prune_session_pointers(sessions_dir, max_age_seconds=7 * 86400):
    try:
        cutoff = time.time() - max_age_seconds
        for item in sessions_dir.glob("*.json"):
            try:
                if item.is_file() and item.stat().st_mtime < cutoff:
                    item.unlink(missing_ok=True)
            except (OSError, ValueError, TypeError):
                pass
    except (OSError, ValueError, TypeError):
        pass


def write_session_pointer(session_id, root):
    if not valid_session_id(session_id):
        return
    sessions_dir = user_home() / "sessions"
    try:
        sessions_dir.mkdir(parents=True, exist_ok=True)
        prune_session_pointers(sessions_dir)
        ptr_file = sessions_dir / f"{session_id}.json"
        atomic_write(ptr_file, dump_json({"store": str(root.resolve()), "time": now()}))
    except (OSError, ValueError, TypeError):
        pass


def discover_hook_store(payload):
    cwd = payload.get("cwd") if isinstance(payload, dict) and isinstance(payload.get("cwd"), str) else os.getcwd()
    root = find_store(cwd)
    if root is not None:
        return root
    proj_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if proj_dir:
        try:
            cand = find_store(proj_dir)
            if cand is not None:
                return cand
        except (OSError, RuntimeError):
            pass
    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    if valid_session_id(session_id):
        try:
            ptr_file = user_home() / "sessions" / f"{session_id}.json"
            if ptr_file.is_file():
                data = json.loads(ptr_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    store_val = data.get("store")
                    if isinstance(store_val, str) and store_val:
                        cand = Path(store_val)
                        if cand.name == STORE_DIR and (cand / "state.json").is_file():
                            return cand
        except (OSError, ValueError, TypeError):
            pass
    return None


def hook_stop(payload):
    if not isinstance(payload, dict) or payload.get("stop_hook_active") is True:
        return ""
    root = discover_hook_store(payload)
    if root is None:
        return ""
    message = payload.get("last_assistant_message")
    if not isinstance(message, str):
        transcript = payload.get("transcript_path")
        message = last_message_from_transcript(transcript) if isinstance(transcript, str) and transcript else ""
    if not message.strip():
        return ""  # nothing to judge (malformed input or no transcript): never block blindly
    try:
        store = Store(root)
        missing = ungated(store)
        fingerprint = store_fingerprint(store)
    except UsageError as exc:
        reason = (f"image-studio: project store is corrupt: {exc}. Repair or restore {root} (state.json, "
                  "defects.jsonl) before claiming anything; report Checked / Not checked / Still failing meanwhile.")
        return block_once(root, payload, message, "corrupt:" + str(exc), reason)
    if store.state["deliverables"] and not missing:
        return ""
    if allowed_final_message(message, store=store):
        return ""
    if store.state["deliverables"]:
        reason = (f"image-studio: no passing gate for: {', '.join(missing)}. Either run {SCRIPT_HINT} gate "
                  "--deliverable NAME until it exits 0 (inspect every crop, record verdicts), or end your message "
                  "with the gate's report under the headings Checked / Not checked / Still failing, or ask the user "
                  "a question.")
    else:
        reason = (f"image-studio: this project has no approved deliverable; approve deliverable first "
                  f"({SCRIPT_HINT} approve deliverable --name NAME --file FILE --width W --height H --format PNG) "
                  "and run the gate, or end with a Checked / Not checked / Still failing report, or ask the user a "
                  "question.")
    return block_once(root, payload, message, fingerprint, reason)


def hook_session_start(payload):
    root = discover_hook_store(payload) if isinstance(payload, dict) else None
    if root is None:
        return ""
    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    write_session_pointer(session_id, root)
    try:
        lines = build_brief(Store(root), 40)
    except UsageError as exc:
        return f"image-studio: project store is corrupt: {exc}"
    return "\n".join(["image-studio project memory (state the 3-5 most relevant lines before working):"] + lines)


def run_hook(argv):
    """Hook entry: always exit 0; print only the hook output, never an error."""
    sys.stderr = io.StringIO()  # discarded: a hook must never print errors
    try:
        mode = argv[0] if argv else ""
        raw = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except ValueError:
            payload = None
        if mode == "stop":
            out = hook_stop(payload) if payload is not None else ""
        elif mode == "session-start":
            out = hook_session_start(payload or {})
        else:
            out = ""
        if out:
            sys.stdout.write(out + "\n")
            sys.stdout.flush()
    except BaseException:
        pass
    return 0


# ---------------------------------------------------------------- CLI

EPILOG = """\
subcommands:
  init --project PATH --brand ID         create PATH/.image-studio/ (state.json, defects.jsonl, masters/)
  approve master --name N --file F --role shape|color|logo|layout [--note T] [--quote T]
                                         copy F into .image-studio/masters/ and record its sha256;
                                         replacing an existing master with another file needs --quote
  approve deliverable --name N --file F [--width W --height H --format PNG|JPEG|WEBP|ZIP]
                      [--alpha required|forbidden|any] [--quote T]
                                         record the spec (needed the first time) and the current file hash;
                                         changing an existing spec needs --quote with the user's words
  defect add --deliverable N --bbox x0,y0,x1,y1 --kind logo|seam|artifact|scope|color|other --note T
             [--master N] [--member ZIP_ENTRY] [--source user|agent] [--quote T]
                                         record a defect on the approved current file; prints its id (D1, D2, ...);
                                         a box under 16x16 px or 0.1% of the image needs --quote
  defect close --id D1 --status resolved|wontfix --note T [--quote T]
                                         wontfix needs --quote with the user's words
  brief [--max-lines 40]                 bounded snapshot; never drops open defects
  gate --deliverable N [--file F] [--run RUN] [--iou-threshold 0.90]
                                         new run (crops + checklist.json) or re-check RUN with its verdicts.json;
                                         the threshold can only be raised
  verdict --run RUN --id D1 --status pass|fail|uncertain --evidence T [--reviewer self|independent] [--crop 100|200]
  pref add [--brand B] --rule T --check T [--evidence T] [--confirmed]
                                         write ${IMAGE_STUDIO_HOME:-~/.image-studio}[/brands/B]/preferences.md
                                         (cap 1500 chars)
  hook session-start | hook stop         plugin hooks: read hook JSON on stdin, always exit 0; while any
                                         deliverable lacks a valid gate, stop blocks (once per message and store
                                         state) every final message that is not a Checked / Not checked /
                                         Still failing report or a question to the user

approve, defect, brief, gate and verdict find the store by walking up from --project or the current folder.
init creates it; pref add does not use the project store; hooks use the cwd from the hook input.
exit codes: 0 ok / gate pass, 1 gate fail, 2 bad input or no store
"""


def build_parser():
    parser = argparse.ArgumentParser(prog="studio_state.py", description=__doc__.split("\n\n")[0],
                                     epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", help="folder to search upward from for .image-studio/ (default: current folder)")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    p = sub.add_parser("init", help="create the project store")
    p.add_argument("--project", required=True, help="project folder (never defaults to home)")
    p.add_argument("--brand", required=True, help="brand or client id, e.g. acme")
    p.set_defaults(func=cmd_init)

    approve = sub.add_parser("approve", help="record an approved master or deliverable").add_subparsers(
        dest="what", metavar="master|deliverable")
    approve.required = True
    p = approve.add_parser("master", parents=[common], help="copy and hash an approved master file")
    p.add_argument("--name", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--role", required=True, choices=ROLES)
    p.add_argument("--note")
    p.add_argument("--quote", help="the user's words approving it")
    p.set_defaults(func=cmd_approve_master)
    p = approve.add_parser("deliverable", parents=[common], help="record a deliverable spec and current file")
    p.add_argument("--name", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--format", help="PNG, JPEG, WEBP or ZIP")
    p.add_argument("--alpha", choices=ALPHA_RULES)
    p.add_argument("--quote", help="the user's words approving it (required when the spec changes)")
    p.set_defaults(func=cmd_approve_deliverable)

    defect = sub.add_parser("defect", help="add or close a defect").add_subparsers(dest="what", metavar="add|close")
    defect.required = True
    p = defect.add_parser("add", parents=[common], help="record a defect with a bbox in deliverable pixels")
    p.add_argument("--deliverable", required=True)
    p.add_argument("--bbox", required=True, nargs="+", help="x0,y0,x1,y1 (x1, y1 exclusive) or four numbers")
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--note", required=True)
    p.add_argument("--master", help="master name for logo defects (enables the objective logo check)")
    p.add_argument("--member", help="image inside a ZIP deliverable")
    p.add_argument("--source", choices=("user", "agent"), default="user")
    p.add_argument("--quote", help="the user's words; required for a bbox under 16x16 px or 0.1%% of the image")
    p.set_defaults(func=cmd_defect_add)
    p = defect.add_parser("close", parents=[common], help="mark a defect resolved or wontfix")
    p.add_argument("--id", required=True)
    p.add_argument("--status", required=True, choices=("resolved", "wontfix"))
    p.add_argument("--note", required=True)
    p.add_argument("--quote", help="the user's words; required for wontfix")
    p.set_defaults(func=cmd_defect_close)

    p = sub.add_parser("brief", parents=[common], help="print the bounded project snapshot")
    p.add_argument("--max-lines", type=int, default=40)
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("gate", parents=[common], help="evidence gate: exit 0 only when everything passes")
    p.add_argument("--deliverable", required=True)
    p.add_argument("--file", help="file to check (default: the approved path)")
    p.add_argument("--run", help="re-check an existing run with its verdicts.json instead of starting a new run")
    p.add_argument("--iou-threshold", type=float, default=DEFAULT_IOU, help="logo IoU floor, 0.90 to 1 (raise only)")
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser("verdict", parents=[common], help="record a verdict for one defect in a gate run")
    p.add_argument("--run", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--status", required=True, choices=("pass", "fail", "uncertain"))
    p.add_argument("--evidence", required=True)
    p.add_argument("--reviewer", choices=("self", "independent"), default="self")
    p.add_argument("--crop", choices=("100", "200"), default="100")
    p.set_defaults(func=cmd_verdict)

    pref = sub.add_parser("pref", help="user preferences").add_subparsers(dest="what", metavar="add")
    pref.required = True
    p = pref.add_parser("add", help="add a preference (proposed unless --confirmed)")
    p.add_argument("--brand", help="brand id; omit for general preferences")
    p.add_argument("--rule", required=True)
    p.add_argument("--check", required=True)
    p.add_argument("--evidence")
    p.add_argument("--confirmed", action="store_true")
    p.set_defaults(func=cmd_pref_add)

    p = sub.add_parser("hook", help="plugin hook modes (always exit 0)")
    p.add_argument("mode", choices=("session-start", "stop"))
    return parser


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["hook"]:
        return run_hook(argv[1:])
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
    except Exception as exc:  # never a traceback
        print(f"error: unexpected {exc.__class__.__name__}: {exc}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
