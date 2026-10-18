#!/usr/bin/env python3
"""Project memory and evidence gate for image-studio.

Keeps a per-project store in `<project>/.image-studio/` (approved deliverables,
user decisions, and every defect ever reported) and a bounded user preference
file in `${IMAGE_STUDIO_HOME:-~/.image-studio}`. The `gate` subcommand is the only way
to prove a deliverable is done: the file must be the approved one, match its spec,
every resolved defect must show changed pixels, and every recorded defect needs
a verdict that names a crop made in the same gate run.
`hook session-start` and `hook stop` are thin wrappers for Claude Code and Codex plugin
hooks; they always exit 0 and print nothing on errors.

Exit codes: 0 success or gate pass, 1 gate fail or edit-check found changes outside the
box, 2 bad input or missing store.
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
try: import fcntl
except ImportError: fcntl = None  # Windows: no lock; lessons are added one at a time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

STORE_DIR = ".image-studio"
SCHEMA_VERSION = 1
PREF_CAP = 1500
CROP_MARGIN = 16
MIN_EVIDENCE = 10
NOTE_LIMIT = 120
MIN_BOX = 16           # smallest defect box side (px) without a user quote
MIN_BOX_SHARE = 0.001  # smallest defect box area (share of the image) without a user quote
CHANGE_LEVEL = 8       # per-channel difference that counts as a changed pixel
CARD_LIMIT = 2400
LESSONS_SHOWN = 5      # lessons printed in the session card and brief
TASTE_SHOWN = 6        # taste notes printed in the session card and brief
BRAND_CAP = 4000        # characters in one brand.json
LONG_CHAT_BYTES = 25 << 20  # a transcript this large resends a long history on every step
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
ASPECTS = ("color", "line", "composition", "detail", "lighting", "text", "style", "other")
MIN_CHANGED = 0.05     # share of changed pixels a resolved defect's box needs
MIN_CHANGED_REQUEST = 0.005  # a requested change (kind scope), e.g. a new date in a text line, changes few pixels
MAX_MEMBER_BYTES = 256 << 20
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DEFECT_ID_RE = re.compile(r"^D([1-9][0-9]*)$")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
KINDS = ("logo", "seam", "artifact", "scope", "color", "other")
ALPHA_RULES = ("required", "forbidden", "any")
FORMATS = {"PNG": "PNG", "JPEG": "JPEG", "JPG": "JPEG", "WEBP": "WEBP", "ZIP": "ZIP"}
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PREF_LINE = re.compile(r"^- \[(confirmed|proposed)\] (.+)$")
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_HINT = "python3 " + shlex.quote(os.path.abspath(__file__))

# Message patterns cover English and Vietnamese (the owner's language); keep both when editing.
REPORT_HEADINGS = tuple(
    re.compile(r"(?:^|[\n.;|])\s*[\s#*>_|-]*(" + words + r")[*_]*\s*(:|\s*$)", re.I | re.M)
    for words in ("checked|đã kiểm", "not checked|chưa kiểm", "still failing|còn lỗi")
)

NEGATION_PAT = re.compile(
    r"(?:\b(?:not|never|no|nothing|isnt|isn't|arent|aren't|havent|haven't|hasnt|hasn't|wasnt|wasn't|cannot)\b|n't\b|\b(?:chưa|không)\b)(?:\s+\w+){0,3}"
    r"|\bxong\s+(?:đợt|bước|phần|lượt|vòng)\s+này\b|\bdone\s+with\s+this\s+(?:step|round|part)\b",
    re.I,
)

# A sentence that also says what is still left is a progress update, not a completion claim.
PROGRESS_PAT = re.compile(
    r"\b(?:still|next|then|remaining|left to|working on|in progress|will|đang|vẫn|còn|tiếp|sẽ|sau đó)\b",
    re.I,
)

COMPLETION_PAT = re.compile(
    r"\b(?:"
    r"done|finished|complete(?:d)?|fixed|resolved|delivered|all\s+good|good\s+to\s+go|"
    r"(?:is|are|now)\s+ready|ready\s+(?:to|for)\s+(?:deliver|delivery|use|ship|download)|"
    r"final\s+(?:file|version|image|poster)|"
    r"xong|hoàn\s+thành|hoàn\s+tất|đã\s+fix|ổn\s+rồi|sẵn\s+sàng|bản\s+cuối|"
    r"đã\s+giao|bàn\s+giao|giao\s+(?:ảnh|file|poster)"
    r")\b",
    re.I,
)


def claims_completion(text):
    """True when any sentence claims the work is done. A question ("Is it done?") claims nothing,
    but a claim followed by a question ("Done. Anything else?") still counts."""
    text = unicodedata.normalize("NFC", text or "")
    for sentence in re.findall(r"[^.!?？\n]+[.!?？\n]?", text):
        if sentence.rstrip().endswith(("?", "？")): continue
        masked = NEGATION_PAT.sub(" ", sentence)
        if COMPLETION_PAT.search(masked) and not PROGRESS_PAT.search(masked): return True
    return False


EMPTY_SECTION = re.compile(r"^[\s*_#>|:-]*(?:none|nothing|\(none\)|n/a|không|không có|-)?[\s*_.]*$", re.I)


def admits_unfinished(text):
    """True for a Checked / Not checked / Still failing report that names something still unchecked or failing.
    A report whose open sections are all empty ("Still failing: none") is a completion claim like any other."""
    t = unicodedata.normalize("NFC", text or "")
    hits = [(m.start(), m.end(), i) for i, h in enumerate(REPORT_HEADINGS) for m in h.finditer(t)]
    if {i for _, _, i in hits} != {0, 1, 2}: return False
    hits.sort()
    for n, (start, end, i) in enumerate(hits):
        if i == 0: continue  # "Checked" lists what passed
        body = t[end:hits[n + 1][0] if n + 1 < len(hits) else len(t)]
        if any(not EMPTY_SECTION.match(line) for line in body.splitlines()): return True
    return False


def valid_session_id(session_id):
    return isinstance(session_id, str) and session_id not in (".", "..") and bool(SESSION_ID_RE.match(session_id))


class UsageError(Exception):
    """Bad input or missing store: reported as one line and exit code 2."""


# ---------------------------------------------------------------- small helpers

def now(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def sha256_bytes(data): return hashlib.sha256(data).hexdigest()
def dump_json(value): return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
def has_alpha(img): return img.mode in ("RGBA", "LA", "PA", "RGBa", "La") or "transparency" in img.info
def count_on(mask): return mask.histogram()[255]
def spec_text(spec): return f"{spec.get('width')}x{spec.get('height')} {spec.get('format')} alpha {spec.get('alpha')}"
def user_home(): return Path(os.environ.get("IMAGE_STUDIO_HOME") or (Path.home() / STORE_DIR)).expanduser()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path, data):
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
        try: os.unlink(tmp)
        except OSError: pass
        raise


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
    if required and not value: raise UsageError(f"{label} must be nonempty text")
    if "\n" in value or "\r" in value: raise UsageError(f"{label} must be a single line")
    return value


def short(text, limit=NOTE_LIMIT):
    text = str(text or "")
    return text if len(text) <= limit else text[:limit - 3] + "..."


def plugin_version():
    for manifest in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        try: version = json.loads((PLUGIN_ROOT / manifest).read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError, AttributeError): continue
        if isinstance(version, str) and version: return version
    return None


def pil():
    try:
        from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat, PngImagePlugin
    except ImportError:
        raise UsageError("Pillow is required: uv run --with pillow python3 ... (or pip install pillow)") from None
    res = getattr(Image, "Resampling", Image)
    return types.SimpleNamespace(Image=Image, ImageChops=ImageChops, ImageDraw=ImageDraw, ImageFilter=ImageFilter, ImageStat=ImageStat,
                                 PngImagePlugin=PngImagePlugin, NEAREST=res.NEAREST, BILINEAR=res.BILINEAR)


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
        for key, kind in (("deliverables", dict), ("decisions", list), ("brand", str)):
            if not isinstance(state.get(key), kind):
                raise UsageError(f"{self.state_path}: state.json field {key!r} is missing or has the wrong type")
        state.setdefault("gates", {})
        return state

    def save(self): atomic_write(self.state_path, dump_json(self.state))

    def defects(self):
        if not self.defects_path.exists(): return []
        items = []
        for n, line in enumerate(self.defects_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip(): continue
            try: item = json.loads(line)
            except ValueError: raise UsageError(f"{self.defects_path}:{n}: not valid JSON") from None
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise UsageError(f"{self.defects_path}:{n}: defect must be an object with an id")
            items.append(item)
        return items

    def save_defects(self, items):
        atomic_write(self.defects_path, "".join(json.dumps(i, sort_keys=True, ensure_ascii=False) + "\n" for i in items))

    def resolve(self, stored):
        path = Path(stored)
        return path if path.is_absolute() else self.project / path

    def relative(self, path):
        path = Path(path).resolve()
        try: return path.relative_to(self.project.resolve()).as_posix()
        except ValueError: return str(path)

    def decide(self, text, quote):
        self.state["decisions"].append({"time": now(), "text": text, "quote": quote or ""})

    def deliverable(self, name):
        item = self.state["deliverables"].get(name)
        if not isinstance(item, dict):
            known = ", ".join(sorted(self.state["deliverables"])) or "none"
            raise UsageError(f"unknown deliverable {name!r} (known: {known}); run approve deliverable first")
        return item


def find_store(start):
    try: home = user_home().resolve()
    except (OSError, RuntimeError): home = None
    path = Path(start).expanduser().resolve()
    for folder in [path] + list(path.parents):
        candidate = folder / STORE_DIR
        if home is not None and candidate.resolve() == home: continue
        if (candidate / "state.json").is_file(): return candidate
    return None


def open_store(project):
    start = Path(project).expanduser() if project else Path.cwd()
    if project and not start.is_dir(): raise UsageError(f"--project {project} is not a folder")
    root = find_store(start)
    if root is None:
        raise UsageError(f"no {STORE_DIR}/ store found from {start.resolve()} upward; "
                         f"run: {SCRIPT_HINT} init --project PATH --brand ID")
    return Store(root)


# ---------------------------------------------------------------- images

def load_image(data):
    P = pil()
    with P.Image.open(io.BytesIO(data)) as img:
        img.load()
        fmt, copy = img.format, img.copy()
    copy.format = fmt
    return copy


_DECODED = {}


def open_image(path, member=None):
    if member is None:
        # A gate run crops every defect from the same file; decode it once per process.
        try: st = Path(path).stat(); key = (str(Path(path).resolve()), st.st_mtime_ns, st.st_size)
        except OSError: key = None
        if key not in _DECODED:
            img = load_image(Path(path).read_bytes())
            if key is None: return img
            _DECODED.clear(); _DECODED[key] = img
        copy = _DECODED[key].copy()
        copy.format = _DECODED[key].format  # Image.copy() drops the format the spec check reads
        return copy
    with zipfile.ZipFile(path) as archive:
        info = member if isinstance(member, zipfile.ZipInfo) else archive.getinfo(member)
        if info.file_size > MAX_MEMBER_BYTES: raise ValueError(f"{info.filename} is larger than {MAX_MEMBER_BYTES >> 20} MB")
        data = archive.read(info)
    return load_image(data)


def zip_images(path):
    names = []
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if not info.is_dir() and PurePosixPath(info.filename).suffix.lower() in IMAGE_SUFFIXES:
                    names.append(info.filename)
    except Exception: pass
    return names


def target_image(path, spec, defect):
    member = defect.get("member")
    if spec.get("format") == "ZIP":
        if member: return open_image(path, member)
        names = zip_images(path)
        if names: return open_image(path, names[0])
    return open_image(path)


def region_crop(img, bbox):
    x0, y0, x1, y1 = bbox
    return img.crop((min(x0, img.size[0]), min(y0, img.size[1]), min(x1, img.size[0]), min(y1, img.size[1]))).convert("RGBA")


def region_hash(img, bbox):
    crop = region_crop(img, bbox)
    return sha256_bytes(f"{crop.size[0]}x{crop.size[1]}:".encode() + crop.tobytes())


def changed_share(before, after):
    if before.size != after.size: return 1.0
    return count_on(changed_mask(before, after)) / float(before.size[0] * before.size[1] or 1)


def alpha_problem(img, rule):
    transparent = has_alpha(img) and (img.convert("RGBA").getchannel("A").getextrema()[0] < 255)
    if rule == "required" and not transparent: return "alpha required but the image has no transparent pixels"
    if rule == "forbidden" and transparent: return "alpha forbidden but the image has transparent pixels"
    return None


def image_problems(img, spec, label):
    problems = []
    if img.size != (spec.get("width"), spec.get("height")):
        problems.append(f"{label}: size {img.size[0]}x{img.size[1]}, spec {spec.get('width')}x{spec.get('height')}")
    issue = alpha_problem(img, spec.get("alpha", "any"))
    if issue: problems.append(f"{label}: {issue}")
    return problems


# ---------------------------------------------------------------- init / approve / defect

def cmd_init(args):
    brand = ident(args.brand, "--brand")
    project = Path(args.project).expanduser()
    if not project.is_dir(): raise UsageError(f"--project {project} is not an existing folder")
    project = project.resolve()
    root = project / STORE_DIR
    if project == Path.home().resolve() or root.resolve() == user_home().resolve():
        raise UsageError("refusing to create a project store in the home folder; pass the project folder with --project")
    ancestor = find_store(project.parent) if project.parent != project else None
    if ancestor is not None:
        raise UsageError(f"{ancestor} already covers this folder; use that store (or pass its project) instead of creating a nested one")
    if (root / "state.json").exists():
        store = Store(root)
        if store.state["brand"] != brand: raise UsageError(f"{root} already exists for brand {store.state['brand']!r}, not {brand!r}")
        print(root); return 0
    root.mkdir(parents=True, exist_ok=True)
    state = {"schema_version": SCHEMA_VERSION, "brand": brand, "deliverables": {}, "decisions": [], "gates": {}}
    atomic_write(root / "state.json", dump_json(state))
    if not (root / "defects.jsonl").exists(): atomic_write(root / "defects.jsonl", "")
    print(root); return 0


def existing_file(value, label):
    path = Path(value).expanduser()
    if not path.is_file(): raise UsageError(f"{label} {value} is not an existing file")
    return path


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
            if value <= 0: raise UsageError(f"--{key} must be a positive integer")
            spec[key] = value
    if args.format is not None:
        fmt = FORMATS.get(args.format.upper())
        if fmt is None: raise UsageError(f"--format must be one of {', '.join(sorted(set(FORMATS.values())))}")
        spec["format"] = fmt
    if args.alpha is not None: spec["alpha"] = args.alpha
    spec.setdefault("alpha", "any")
    missing = [k for k in ("width", "height", "format") if k not in spec]
    if missing: raise UsageError(f"first approval of {name!r} needs --{' --'.join(missing)}")
    quote = text_arg(args.quote, "--quote", False)
    changed = bool(old_spec) and spec != old_spec
    if changed and not quote:
        raise UsageError(f"changing the spec of {name!r} ({spec_text(old_spec)} → {spec_text(spec)}) needs --quote with the user's words")
    digest = sha256_file(path)
    store.state["deliverables"][name] = {"spec": spec, "current_sha256": digest, "path": store.relative(path)}
    text = f"approved deliverable {name} = {path.name} ({spec_text(spec)})"
    if changed: text += f"; spec changed {spec_text(old_spec)} → {spec_text(spec)}"
    store.decide(text, quote)
    store.save()
    print(f"Approved deliverable {name}: {store.relative(path)} sha256 {digest}")
    return 0


def parse_bbox(values):
    raw = values[0].split(",") if len(values) == 1 else values
    try: box = [int(str(v).strip()) for v in raw]
    except ValueError: raise UsageError("--bbox must be 4 integers: x0,y0,x1,y1") from None
    if len(box) != 4 or box[0] < 0 or box[1] < 0 or box[2] <= box[0] or box[3] <= box[1]:
        raise UsageError("--bbox needs 0 <= x0 < x1 and 0 <= y0 < y1 (x1, y1 exclusive)")
    return box


def cmd_defect_add(args):
    store = open_store(args.project)
    item = store.deliverable(args.deliverable)
    spec = item.get("spec") or {}
    box = parse_bbox(args.bbox)
    if box[2] > spec.get("width", box[2]) or box[3] > spec.get("height", box[3]):
        raise UsageError(f"--bbox {box} is outside the deliverable size {spec.get('width')}x{spec.get('height')}")
    note = text_arg(args.note, "--note")
    path = store.resolve(item.get("path", ""))
    if not path.is_file() or sha256_file(path) != item.get("current_sha256"):
        raise UsageError(f"{path} is missing or differs from the approved file; run approve deliverable for the file "
                         "the user is looking at, then add the defect")
    record = {"deliverable": args.deliverable, "bbox": box, "kind": args.kind, "source": args.source,
              "status": "open", "note": note, "reported_sha256": item["current_sha256"]}
    quote = text_arg(args.quote, "--quote", False)
    members = zip_images(path) if spec.get("format") == "ZIP" else []
    if len(members) > 1:
        raise UsageError(f"{path.name} holds {len(members)} images; approve the image that has the defect as its "
                         "own deliverable, then add the defect there")
    try:
        image = target_image(path, spec, record)
        record["region_hash"] = region_hash(image, box)
        reported = region_crop(image, box)
    except UsageError: raise
    except Exception as exc: raise UsageError(f"cannot read the defect region from {path.name}: {exc}") from None
    width, height = box[2] - box[0], box[3] - box[1]
    small = width < MIN_BOX or height < MIN_BOX or width * height < MIN_BOX_SHARE * image.size[0] * image.size[1]
    if small and not quote:
        raise UsageError(f"--bbox {width}x{height} is too small to prove a fix (needs >= {MIN_BOX}x{MIN_BOX} px and "
                         f">= {MIN_BOX_SHARE:.1%} of the image); draw a larger box or pass --quote with the user's words")
    if quote: record["quote"] = quote
    defects = store.defects()
    # A requested change (kind scope with the user's words: new text, a removed element) is not a miss, so it needs no lesson.
    request = args.kind == "scope" and bool(quote)
    after_delivery = args.source == "user" and not request and gate_is_valid(store, args.deliverable, defects)
    if after_delivery: record["needs_lesson"] = True
    numbers = [int(m.group(1)) for m in (DEFECT_ID_RE.match(d["id"]) for d in defects) if m]
    record["id"] = f"D{max(numbers, default=0) + 1}"
    (store.root / "defects").mkdir(exist_ok=True)
    buf = io.BytesIO()
    reported.save(buf, "PNG")
    record["reported_crop"] = f"defects/{record['id']}-reported.png"
    atomic_write(store.root / record["reported_crop"], buf.getvalue())
    record["history"] = [{"time": now(), "action": "add", "status": "open", "note": note}]
    defects.append(record)
    store.save_defects(defects)
    print(f"Added defect {record['id']}")
    if after_delivery:
        print(f"{args.deliverable} had passed the gate, so this is a miss after delivery. Record what to do differently:\n"
              f"{SCRIPT_HINT} lesson add --defect {record['id']} --mistake \"...\" --cause \"...\" --check \"...\"")
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
            if quote: entry["quote"] = quote
            item.setdefault("history", []).append(entry)
            store.save_defects(defects)
            print(f"{args.id} -> {args.status}")
            return 0
    raise UsageError(f"unknown defect id {args.id!r}")


# ---------------------------------------------------------------- preferences

def pref_paths(brand):
    home = user_home()
    return (home / "brands" / brand / "preferences.md" if brand else None), (home / "preferences.md")


def read_prefs(path):
    if path is None: return []
    try: text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError): return []
    return [(m.group(1), m.group(2)) for m in map(PREF_LINE.match, text.splitlines()) if m]


def cmd_pref_add(args):
    brand = ident(args.brand, "--brand") if args.brand is not None else None
    rule, check, evidence = text_arg(args.rule, "--rule"), text_arg(args.check, "--check"), text_arg(args.evidence, "--evidence", False)
    for label, val in (("--rule", rule), ("--check", check), ("--evidence", evidence)):
        if EMAIL_RE.search(val): raise UsageError(f"{label} looks like it contains an email address; preferences must not store accounts")
    path = pref_paths(brand)[0] if brand else pref_paths(None)[1]
    status = "confirmed" if args.confirmed else "proposed"
    entry = f"- [{status}] {rule} — check: {check}" + (f" — evidence: {evidence}" if evidence else "")
    try: text = path.read_text(encoding="utf-8") if path.is_file() else f"# Image Studio preferences: {brand or 'general'}\n\n"
    except (OSError, UnicodeDecodeError) as exc: raise UsageError(f"cannot read preferences at {path}: {exc}") from None
    lines = text.splitlines()
    prefix = re.compile(r"^- \[(confirmed|proposed)\] " + re.escape(rule) + " — check: ")
    hits = [i for i, line in enumerate(lines) if prefix.match(line)]
    if hits:
        old = prefix.match(lines[hits[0]]).group(1)
        if old == "confirmed" or old == status: raise UsageError(f"rule already recorded as {old} in {path}")
        lines[hits[0]] = entry
    else: lines.append(entry)
    new_text = "\n".join(lines) + "\n"
    if len(new_text) > PREF_CAP:
        raise UsageError(f"{path} would be {len(new_text)} characters (cap {PREF_CAP}); consolidate or remove entries before adding more")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, new_text)
    except OSError as exc: raise UsageError(f"cannot write preferences at {path}: {exc}") from None
    print(f"{path}: {entry}")
    return 0


# ---------------------------------------------------------------- lessons

def lessons_path(): return user_home() / "lessons.jsonl"


def read_lessons(text=None):
    if text is None:
        try: text = lessons_path().read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError): return []
    out = []
    for line in text.splitlines():
        try: item = json.loads(line)
        except ValueError: continue
        if isinstance(item, dict) and isinstance(item.get("id"), str) and all(isinstance(item.get(k), str) for k in ("mistake", "check")):
            out.append(item)
    return out


def lesson_line(item):
    worked = f"; worked: {short(item['worked'], 70)}" if isinstance(item.get("worked"), str) else ""
    return f"- {item['id']} [{item.get('kind', 'other')}] {short(item['mistake'], 90)} -> check: {short(item['check'], 90)}{worked}"


def relevant_lessons(lessons, brand, kinds, limit=LESSONS_SHOWN):
    def number(l):
        m = re.match(r"^L([1-9][0-9]*)$", l["id"])
        return int(m.group(1)) if m else 0
    ranked = sorted(lessons, key=lambda l: (l.get("brand") == brand, l.get("kind") in kinds, str(l.get("time")), number(l)), reverse=True)
    return ranked[:limit]


def lesson_linked(lessons, root, defect_id):
    project = str(root.resolve())
    return any(l.get("project") == project and l.get("defect") == defect_id for l in lessons)


def cmd_lesson_add(args):
    mistake, cause, check = text_arg(args.mistake, "--mistake"), text_arg(args.cause, "--cause"), text_arg(args.check, "--check")
    for label, val in (("--mistake", mistake), ("--cause", cause), ("--check", check)):
        if EMAIL_RE.search(val): raise UsageError(f"{label} looks like it contains an email address; lessons must not store accounts")
    record = {"mistake": mistake, "cause": cause, "check": check, "kind": args.kind, "time": now()}
    worked = text_arg(args.worked, "--worked", False)
    if worked:
        if EMAIL_RE.search(worked): raise UsageError("--worked looks like it contains an email address; lessons must not store accounts")
        record["worked"] = worked
    store = None
    try: store = open_store(args.project)
    except UsageError:
        if args.defect: raise
    if store is not None:
        record["project"] = str(store.root.resolve())
        record["brand"] = store.state.get("brand")
    if args.brand is not None: record["brand"] = ident(args.brand, "--brand")
    if args.defect:
        defect = next((d for d in store.defects() if d.get("id") == args.defect), None)
        if defect is None: raise UsageError(f"unknown defect id {args.defect!r}")
        record["defect"] = args.defect
        if args.kind is None: record["kind"] = defect.get("kind")
    record["kind"] = record.get("kind") or "other"
    path = lessons_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a+", encoding="utf-8") as handle:
            if fcntl is not None: fcntl.flock(handle, fcntl.LOCK_EX)
            handle.seek(0)
            text = handle.read()
            lessons = read_lessons(text)
            numbers = [int(l["id"][1:]) for l in lessons if re.match(r"^L[1-9][0-9]*$", l["id"])]
            record["id"] = f"L{max(numbers, default=0) + 1}"
            handle.write(("" if not text or text.endswith("\n") else "\n") + json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
    except (OSError, UnicodeDecodeError) as exc: raise UsageError(f"cannot write lessons at {path}: {exc}") from None
    print(f"Added lesson {record['id']}")
    def jobs(items):
        return {l.get("project") for l in items if l.get("brand") == record.get("brand") and l.get("kind") == record["kind"] and l.get("project")}
    brand_prefs = read_prefs(pref_paths(record.get("brand"))[0]) if record.get("brand") else []
    covered = any(check.lower() in rule.lower() for _, rule in brand_prefs)
    if record["kind"] != "other" and not covered and len(jobs(lessons)) < 2 <= len(jobs(lessons + [record])):
        brand = f" --brand {record['brand']}" if record.get("brand") else ""
        print(f"This kind of mistake ({record['kind']}) has now happened in 2 jobs. Ask the user whether to make it a rule:\n"
              f"{SCRIPT_HINT} pref add{brand} --rule \"...\" --check \"{short(check, 200)}\"   (add --confirmed only after the user agrees)")
    return 0


def cmd_lesson_list(args):
    lessons = [l for l in read_lessons() if args.brand is None or l.get("brand") == args.brand]
    if not lessons: print("No lessons recorded."); return 0
    for item in lessons: print(lesson_line(item) + f" (cause: {short(item.get('cause', ''), 90)})")
    return 0


# ---------------------------------------------------------------- taste

def taste_path(brand):
    home = user_home()
    return home / "brands" / brand / "taste.jsonl" if brand else home / "taste.jsonl"


def read_taste(brand):
    try: text = taste_path(brand).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError): return []
    out = []
    for line in text.splitlines():
        try: item = json.loads(line)
        except ValueError: continue
        if isinstance(item, dict) and isinstance(item.get("note"), str): out.append(item)
    return out


def newest_taste(brand, limit=TASTE_SHOWN):
    """Brand and general notes merged newest first; a note repeated word for word is shown once."""
    merged = read_taste(brand) + (read_taste(None) if brand else [])
    # Same-second notes keep file order: a later line in a file is newer.
    items = [t for _, t in sorted(enumerate(merged), key=lambda it: (str(it[1].get("time", "")), it[0]), reverse=True)]
    seen, out = set(), []
    for item in items:
        key = " ".join(item["note"].lower().split())
        if key in seen: continue
        seen.add(key); out.append(item)
        if len(out) == limit: break
    return out


def taste_line(item):
    said = f' (user: "{short(item["quote"], 60)}")' if isinstance(item.get("quote"), str) else ""
    return f"- [{item.get('aspect', 'other')}] {short(item['note'], 110)}{said}"


def cmd_taste_add(args):
    note = text_arg(args.note, "--note")
    quote = text_arg(args.quote, "--quote", False)
    for label, val in (("--note", note), ("--quote", quote)):
        if EMAIL_RE.search(val): raise UsageError(f"{label} looks like it contains an email address; taste notes must not store accounts")
    brand = ident(args.brand, "--brand") if args.brand is not None else None
    record = {"note": note, "aspect": args.aspect, "time": now()}
    if quote: record["quote"] = quote
    try: store = open_store(args.project)
    except UsageError: store = None
    if store is not None:
        brand = brand or store.state.get("brand")
        record["project"] = str(store.root.resolve())
        if args.deliverable:
            item = store.deliverable(args.deliverable)
            record["deliverable"], record["sha256"] = args.deliverable, item.get("current_sha256")
    elif args.deliverable: raise UsageError("--deliverable needs a project store")
    path = taste_path(brand)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            if fcntl is not None: fcntl.flock(handle, fcntl.LOCK_EX)
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc: raise UsageError(f"cannot write taste notes at {path}: {exc}") from None
    print(f"Recorded taste for {brand or 'all work'}: {taste_line(record)[2:]}")
    return 0


def cmd_taste_list(args):
    items = read_taste(args.brand)
    if not items: print("No taste notes recorded."); return 0
    for item in items: print(taste_line(item) + f" {item.get('time', '')}")
    return 0


# ---------------------------------------------------------------- brand kit

def brand_path(brand): return user_home() / "brands" / brand / "brand.json"


def read_brand(brand):
    if not brand: return {}
    try: data = json.loads(brand_path(brand).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError): return {}
    if not isinstance(data, dict): return {}
    # Keep only well-formed entries, so a hand-edited file never breaks brief, the card, or brand set.
    kit = {}
    for key in ("colors", "refs"):
        items = data.get(key)
        if isinstance(items, dict):
            kit[key] = {k: v for k, v in items.items() if isinstance(k, str) and isinstance(v, dict)}
    if isinstance(data.get("fonts"), dict):
        kit["fonts"] = {k: v for k, v in data["fonts"].items() if isinstance(k, str) and isinstance(v, str)}
    for key in ("do", "dont"):
        if isinstance(data.get(key), list): kit[key] = [t for t in data[key] if isinstance(t, str)]
    if isinstance(data.get("logo"), dict) and isinstance(data["logo"].get("file"), str): kit["logo"] = data["logo"]
    return kit


def pairs(values, label):
    out = []
    for raw in values or []:
        key, sep, val = raw.partition("=")
        if not sep or not key.strip() or not val.strip(): raise UsageError(f"{label} must look like NAME=VALUE, got {raw!r}")
        if EMAIL_RE.search(raw): raise UsageError(f"{label} looks like it contains an email address")
        out.append((key.strip(), val.strip()))
    return out


def cmd_brand_set(args):
    brand = ident(args.brand, "--brand")
    kit = read_brand(brand)
    for name, val in pairs(args.color, "--color"):
        hexv, _, role = val.partition(":")
        if not HEX_RE.match(hexv): raise UsageError(f"--color {name}: {hexv!r} is not a #RRGGBB hex color")
        kit.setdefault("colors", {})[name] = {"hex": hexv.upper(), "role": role.strip()}
    for role, family in pairs(args.font, "--font"):
        kit.setdefault("fonts", {})[role] = family
    for file_arg, role in pairs(args.ref, "--ref"):
        path = existing_file(file_arg, "--ref")
        kit.setdefault("refs", {})[str(path.resolve())] = {"role": role, "sha256": sha256_file(path)}
    if args.logo:
        path = existing_file(args.logo, "--logo")
        kit["logo"] = {"file": str(path.resolve()), "sha256": sha256_file(path)}
    for label, key, values in (("--do", "do", args.do), ("--dont", "dont", args.dont)):
        for text in values or []:
            text = text_arg(text, label)
            if EMAIL_RE.search(text): raise UsageError(f"{label} looks like it contains an email address")
            if text not in kit.setdefault(key, []): kit[key].append(text)
    for key in args.remove or []:
        section, _, name = key.partition(":")
        if section in ("do", "dont"): kit[section] = [t for t in kit.get(section, []) if t != name]
        elif section == "logo": kit.pop("logo", None)
        elif section in ("colors", "fonts", "refs"):
            target = str(Path(name).expanduser().resolve()) if section == "refs" else name
            if target not in kit.get(section, {}): raise UsageError(f"--remove {key}: not in the brand kit")
            del kit[section][target]
        else: raise UsageError("--remove takes colors:NAME, fonts:ROLE, refs:FILE, do:TEXT, dont:TEXT, or logo")
    kit = {k: v for k, v in kit.items() if v}
    text = dump_json(kit)
    if len(text) > BRAND_CAP: raise UsageError(f"brand kit would be {len(text)} characters (cap {BRAND_CAP}); remove entries first")
    try:
        brand_path(brand).parent.mkdir(parents=True, exist_ok=True)
        atomic_write(brand_path(brand), text)
    except OSError as exc: raise UsageError(f"cannot write {brand_path(brand)}: {exc}") from None
    print("\n".join(brand_lines(brand, kit)))
    return 0


def brand_lines(brand, kit):
    lines = []
    if kit.get("colors"):
        lines.append("Colors: " + ", ".join(f"{n} {c.get('hex')}" + (f" ({c['role']})" if c.get("role") else "") for n, c in kit["colors"].items()))
    if kit.get("fonts"): lines.append("Fonts: " + ", ".join(f"{r}={f}" for r, f in kit["fonts"].items()))
    if kit.get("logo"):
        logo = kit["logo"]; ok = Path(logo["file"]).is_file() and sha256_file(Path(logo["file"])) == logo.get("sha256")
        lines.append(f"Logo: {logo['file']} (composite this exact file; never redraw it)" + ("" if ok else " - MISSING OR CHANGED, ask the user"))
    if kit.get("do"): lines.append("Do: " + "; ".join(kit["do"]))
    if kit.get("dont"): lines.append("Don't: " + "; ".join(kit["dont"]))
    if kit.get("refs"):
        lines.append(f"Approved references ({len(kit['refs'])}; only these and files the user sends may be used as pixels or style refs):")
        for f, r in kit["refs"].items():
            ok = Path(f).is_file() and sha256_file(Path(f)) == r.get("sha256")
            lines.append(f"- {f} [{r.get('role')}]" + ("" if ok else " - MISSING OR CHANGED, ask the user"))
    return [f"Brand kit {brand}: (empty)"] if not lines else [f"Brand kit {brand}:"] + lines


def cmd_brand_show(args):
    brand = args.brand
    if brand is None:
        try: brand = open_store(args.project).state.get("brand")
        except UsageError: raise UsageError("pass --brand, or run inside a project store") from None
    print("\n".join(brand_lines(ident(brand, "--brand"), read_brand(brand))))
    return 0


def brand_card_line(brand):
    kit = read_brand(brand)
    if not kit: return []
    bits = []
    if kit.get("colors"): bits.append("palette " + " ".join(c.get("hex", "") for c in kit["colors"].values()))
    if kit.get("fonts"): bits.append("fonts " + ", ".join(f"{r}={f}" for r, f in kit["fonts"].items()))
    if kit.get("logo"): bits.append("logo file (never redraw)")
    if kit.get("refs"): bits.append(f"{len(kit['refs'])} approved refs")
    if kit.get("dont"): bits.append("don't: " + "; ".join(kit["dont"]))
    return [short("Brand kit: " + " | ".join(bits), 330) + " (brand show for details)"]


# ---------------------------------------------------------------- gate validity

def id_gaps(defects):
    nums = {int(m.group(1)) for m in (DEFECT_ID_RE.match(str(d.get("id"))) for d in defects) if m}
    return [f"D{n}" for n in range(1, max(nums, default=0)) if n not in nums]


def gate_is_valid(store, name, defects):
    item = store.state["deliverables"].get(name) or {}
    gate = store.state.get("gates", {}).get(name)
    if not isinstance(gate, dict) or not isinstance(gate.get("run_id"), str) or not re.match(r"^[A-Za-z0-9-]+$", gate["run_id"]):
        return False
    run_dir = store.root / "gate" / gate["run_id"]
    try:
        checklist = json.loads((run_dir / "checklist.json").read_text(encoding="utf-8"))
        verdicts = json.loads((run_dir / "verdicts.json").read_text(encoding="utf-8")) if (run_dir / "verdicts.json").is_file() else {}
        path = store.resolve(item.get("path", ""))
        current = sha256_file(path) if path.is_file() else None
    except (OSError, ValueError): return False
    if not isinstance(checklist, dict) or not isinstance(verdicts, dict) or checklist.get("deliverable") != name or not current:
        return False
    if not (current == item.get("current_sha256") == checklist.get("sha256") == gate.get("sha256")) or id_gaps(defects):
        return False
    entries = {e.get("id"): e for e in checklist.get("defects", []) if isinstance(e, dict)}
    mine = [d for d in defects if d.get("deliverable") == name]
    if any(d.get("status") == "open" for d in mine) or any(d.get("status") != "wontfix" and d["id"] not in entries for d in mine):
        return False
    if any(d.get("needs_lesson") for d in mine):
        lessons = read_lessons()
        if any(d.get("needs_lesson") and not lesson_linked(lessons, store.root, d["id"]) for d in mine): return False
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


# ---------------------------------------------------------------- brief and session-start

def defect_line(d, limit=NOTE_LIMIT):
    extra = f" master {d['master']}" if d.get("master") else ""
    extra += f" member {d['member']}" if d.get("member") else ""
    box = ",".join(str(v) for v in d.get("bbox") or [])
    note = short(d.get("note", ""), limit=limit) if limit > 0 else ""
    note_part = f": {note}" if note else ""
    return f"{d.get('id')} {d.get('status')} {d.get('deliverable')} [{d.get('kind')}] bbox {box}{extra} ({d.get('source')}){note_part}"


def is_self_verified(run_dir):
    if not run_dir: return False
    vpath = Path(run_dir) / "verdicts.json"
    if not vpath.is_file(): return False
    try:
        vdata = json.loads(vpath.read_text(encoding="utf-8"))
        vdict = vdata.get("verdicts") if isinstance(vdata, dict) and isinstance(vdata.get("verdicts"), dict) else {}
        return any(isinstance(v, dict) and v.get("reviewer") == "self" for v in vdict.values())
    except (OSError, ValueError): return False


def shared_sections(store, defects):
    state = store.state
    delivs = []
    for name, item in sorted(state.get("deliverables", {}).items()):
        gate = state.get("gates", {}).get(name) or {}
        if gate_is_valid(store, name, defects):
            rid = gate.get("run_id")
            rdir = store.root / "gate" / rid if rid else None
            p = "gate passed (self-verified)" if is_self_verified(rdir) else f"gate passed run {rid}"
        else: p = "gate not passed for current file"
        delivs.append(f"- {name}: {spec_text(item.get('spec') or {})}, current {item.get('path')} sha256 {str(item.get('current_sha256'))[:12]}, {p}")
    decs = [f"- {d.get('time')} {short(d.get('text'))}" + (f' (user: "{short(d["quote"])}")' if d.get("quote") else "") for d in state.get("decisions", [])[-3:][::-1]]
    brand_file, gen_file = pref_paths(state.get("brand"))
    prefs = read_prefs(brand_file) + read_prefs(gen_file)
    conf = [f"- {rule}" for status, rule in prefs if status == "confirmed"]
    kinds = {d.get("kind") for d in defects if d.get("status") == "open"}
    lessons = [lesson_line(l) for l in relevant_lessons(read_lessons(), state.get("brand"), kinds)]
    taste = brand_card_line(state.get("brand")) + [taste_line(t) for t in newest_taste(state.get("brand"))]
    return delivs, decs, prefs, conf, lessons, taste


def build_brief(store, max_lines):
    state = store.state
    defects = store.defects()
    cur = plugin_version()
    head = [f"Brand: {state['brand']} | store: {store.root}"]
    if cur: head.append(f"Plugin version: {cur}")
    head.append("Precedence: latest user instruction > project decisions > brand prefs > general prefs.")
    head.append("Commands: run studio_state.py --help for cheat sheet; do not read its source.")
    for gap in id_gaps(defects): head.append(f"WARNING: {gap} missing from defects.jsonl (defects are never deleted, only closed)")
    open_items = [d for d in defects if d.get("status") == "open"]
    head.append(f"Open defects ({len(open_items)}, all listed; gate cannot pass while any is open):" if open_items else "Open defects: none")
    if open_items: head += [f"- {defect_line(d)}" for d in open_items]
    delivs, decs, prefs, conf, lessons, taste = shared_sections(store, defects)
    prop = sum(1 for st, _ in prefs if st == "proposed")
    if prop: head.append(f"Preferences: {prop} proposed, ask the user to confirm (pref add ... --confirmed).")
    sections = [("Deliverables:", delivs)]
    sections += [("Your taste (match it):", taste), ("Lessons from earlier jobs (check these):", lessons), ("Confirmed preferences:", conf), ("Recent decisions:", decs), ("Closed defects (resolved ones are re-checked by the gate):", [f"- {defect_line(d)}" for d in [d for d in defects if d.get("status") != "open"][::-1]])]
    lines = list(head)
    budget = max(0, max_lines - len(lines))
    if sum(len(items) + 1 for _, items in sections if items) > budget: budget -= 1
    omitted = 0
    for title, items in sections:
        if not items: continue
        if budget >= 2:
            take = min(len(items), budget - 1)
            lines.append(title); lines += items[:take]
            budget -= take + 1; omitted += len(items) - take
        else: omitted += len(items) + 1
    if omitted: lines.append(f"... {omitted} lines omitted (run brief --max-lines {max_lines + omitted})")
    return lines


def cmd_brief(args):
    if args.max_lines < 1: raise UsageError("--max-lines must be at least 1")
    print("\n".join(build_brief(open_store(args.project), args.max_lines)))
    return 0


def format_session_start_card(store):
    state = store.state
    defects = store.defects()
    open_items = [d for d in defects if d.get("status") == "open"]
    resolved_items = [d for d in defects if d.get("status") == "resolved"]
    delivs, decs, _, conf, lessons, taste = shared_sections(store, defects)

    for limit in (100, 80, 60, 40, 20, 10, 5, 0):
        lines = [f"image-studio project memory (brand: {state.get('brand')} | store: {store.root}):"]
        lines.append(f"Open defects ({len(open_items)}, all listed; gate cannot pass while any is open):" if open_items else "Open defects: none")
        lines.extend(f"- {defect_line(d, limit=limit)}" for d in open_items)
        if delivs: lines.append("Deliverables:"); lines.extend(delivs)
        if decs: lines.append("Recent decisions:"); lines.extend(decs)
        if taste: lines.append("Your taste (match it):"); lines.extend(taste)
        if lessons: lines.append("Lessons from earlier jobs (check these):"); lines.extend(lessons)
        if conf: lines.append("Confirmed preferences:"); lines.extend(conf)
        if resolved_items: lines.append(f"{len(resolved_items)} resolved - regression-checked by the gate")
        lines.append("When the user approves or praises a result, record what they liked: taste add --aspect ... --note ... --quote \"their words\".")
        lines.append("Commands: run studio_state.py --help; do not read its source.")
        card = "\n".join(lines)
        if len(card) <= CARD_LIMIT: return card
    # Too many open defects for notes: list every open ID (never dropped) and cut the rest.
    head = [lines[0], f"Open defects ({len(open_items)}; run brief for details): " + ", ".join(str(d.get("id")) for d in open_items)]
    tail = lines[-2:]  # the taste reminder and the commands line always stay
    body = []
    for line in lines[2 + len(open_items):-2]:
        if len("\n".join(head + body + [line] + tail)) > CARD_LIMIT: break
        body.append(line)
    return "\n".join(head + body + tail)


# ---------------------------------------------------------------- gate

class Report:
    def __init__(self): self.checked, self.not_checked, self.failing = [], [], []
    def ok(self, text): self.checked.append(text)
    def skip(self, text): self.not_checked.append(text)
    def fail(self, text): self.failing.append(text)
    def passed(self): return not self.failing and not self.not_checked
    def lines(self):
        out = []
        for t, items in (("Checked", self.checked), ("Not checked", self.not_checked), ("Still failing", self.failing)):
            out.append(f"{t}:"); out += [f"- {item}" for item in items] or ["- (none)"]
        return out


def spec_checks(path, spec, report):
    fmt = spec.get("format")
    if fmt == "ZIP":
        if not zipfile.is_zipfile(path): report.fail(f"format: {path.name} is not a ZIP archive (spec ZIP)"); return
        try:
            size = path.stat().st_size
            if size == 0: report.fail(f"spec: {path.name} is empty (0 bytes)"); return
        except OSError as exc: report.fail(f"cannot inspect {path.name}: {exc}"); return
        report.ok(f"spec: {path.name} is a valid ZIP archive ({size} bytes)"); return
    try: img = open_image(path)
    except UsageError: raise
    except Exception as exc: report.fail(f"format: cannot open {path.name} as an image ({exc})"); return
    if img.format != fmt: report.fail(f"format: {path.name} is {img.format}, spec {fmt}")
    problems = image_problems(img, spec, path.name)
    for p in problems: report.fail(p)
    if img.format == fmt and not problems: report.ok(f"spec: {spec['width']}x{spec['height']} {fmt}, alpha {spec['alpha']}")


def render_crops(image, defect_id, crop_box, nonce):
    P = pil()
    crop = image.crop(tuple(crop_box))
    crop = crop.convert("RGBA" if has_alpha(crop) else "RGB")
    info = P.PngImagePlugin.PngInfo()
    info.add_text("image-studio-run", nonce)
    out = {}
    for scale, img in (("100", crop), ("200", crop.resize((crop.size[0] * 2, crop.size[1] * 2), P.NEAREST))):
        buf = io.BytesIO()
        img.save(buf, "PNG", pnginfo=info)
        out[scale] = (f"{defect_id}-{scale}.png", buf.getvalue())
    return out


def crop_box_for(image, bbox):
    x0, y0, x1, y1 = bbox
    w, h = image.size
    return [max(0, x0 - CROP_MARGIN), max(0, y0 - CROP_MARGIN), min(w, x1 + CROP_MARGIN), min(h, y1 + CROP_MARGIN)]


def earlier_pass(store, name, defect_id, crop_box, pixels, limit=20):
    """The newest earlier run whose verdict passed this defect on exactly these pixels, or None.

    The old 100% crop is decoded and hashed, so a carried pass is tied to identical pixels, not to a file name."""
    P = pil()
    gate_dir = store.root / "gate"
    try: runs = sorted((d for d in gate_dir.iterdir() if d.is_dir()), reverse=True)[:limit]
    except OSError: return None
    for run_dir in runs:
        try:
            checklist = json.loads((run_dir / "checklist.json").read_text(encoding="utf-8"))
            verdicts = json.loads((run_dir / "verdicts.json").read_text(encoding="utf-8"))
        except (OSError, ValueError): continue
        if not isinstance(checklist, dict) or not isinstance(verdicts, dict) or checklist.get("deliverable") != name: continue
        if verdicts.get("run_id") != checklist.get("run_id") or verdicts.get("nonce") != checklist.get("nonce"): continue
        entry = next((e for e in checklist.get("defects", []) if isinstance(e, dict) and e.get("id") == defect_id), None)
        verdict = (verdicts.get("verdicts") or {}).get(defect_id) if isinstance(verdicts.get("verdicts"), dict) else None
        if not entry or entry.get("crop_box") != crop_box or not isinstance(verdict, dict) or verdict.get("status") != "pass": continue
        crop = (entry.get("crops") or {}).get("100") or {}
        ev = verdict.get("evidence")
        if verdict.get("crop_sha256") not in {c.get("sha256") for c in (entry.get("crops") or {}).values() if isinstance(c, dict)}: continue
        if not isinstance(ev, str) or len(ev.strip()) < MIN_EVIDENCE or verdict.get("reviewer") not in ("self", "independent"): continue
        try:
            crop_file = run_dir / crop["file"]
            if sha256_file(crop_file) != crop.get("sha256"): continue
            with P.Image.open(crop_file) as old:
                old.load()
                if region_hash(old, [0, 0, old.size[0], old.size[1]]) != pixels: continue
        except (OSError, KeyError, TypeError, ValueError): continue
        return run_dir.name, verdict
    return None


def new_run(store, name, path, digest, spec, defects):
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    run_dir = store.root / "gate" / run_id
    run_dir.mkdir(parents=True)
    nonce = secrets.token_hex(16)
    entries, carried = [], {}
    for defect in defects:
        entry = {"id": defect["id"], "status": defect.get("status"), "kind": defect.get("kind"), "bbox": defect["bbox"], "crops": {}}
        if defect.get("member"): entry["member"] = defect["member"]
        try:
            image = target_image(path, spec, defect)
            entry["crop_box"] = crop_box_for(image, defect["bbox"])
            if entry["crop_box"][2] <= entry["crop_box"][0] or entry["crop_box"][3] <= entry["crop_box"][1]:
                entry["error"] = "bbox is outside the image"
            else:
                for scale, (file_name, data) in render_crops(image, defect["id"], entry["crop_box"], nonce).items():
                    atomic_write(run_dir / file_name, data)
                    entry["crops"][scale] = {"file": file_name, "sha256": sha256_bytes(data)}
                if defect.get("status") == "resolved":
                    found = earlier_pass(store, name, defect["id"], entry["crop_box"], region_hash(image, entry["crop_box"]))
                    if found: carried[defect["id"]] = (found, entry["crops"]["100"]["sha256"])
        except UsageError: raise
        except Exception as exc: entry["crop_box"], entry["error"] = None, f"cannot crop ({exc})"
        entries.append(entry)
    checklist = {"run_id": run_id, "nonce": nonce, "deliverable": name, "file": str(path), "sha256": digest, "created": now(), "defects": entries}
    atomic_write(run_dir / "checklist.json", dump_json(checklist))
    if carried:
        # A resolved defect whose pixels are identical to an earlier passing run keeps that verdict; only changed regions need a new look.
        verdicts = {did: {"status": "pass", "crop_sha256": crop_sha, "reviewer": old["reviewer"], "time": now(), "carried_from": old_run,
                          "evidence": f"unchanged since run {old_run}: {old['evidence'].strip()}"}
                    for did, ((old_run, old), crop_sha) in carried.items()}
        atomic_write(run_dir / "verdicts.json", dump_json({"run_id": run_id, "nonce": nonce, "deliverable": name, "verdicts": verdicts}))
        print(f"Carried {len(carried)} verdict(s) for regions unchanged since an earlier passing run: {', '.join(sorted(carried, key=lambda d: int(d[1:])))}")
    return run_id, run_dir, checklist


def load_run(store, run_id):
    if not isinstance(run_id, str) or not re.match(r"^[A-Za-z0-9-]+$", run_id): raise UsageError(f"bad run id {run_id!r}")
    run_dir = store.root / "gate" / run_id
    if not (run_dir / "checklist.json").is_file(): raise UsageError(f"unknown gate run {run_id!r} (no {run_dir / 'checklist.json'})")
    return run_dir, read_json(run_dir / "checklist.json", "checklist.json")


def check_run_integrity(store, run_id, run_dir, checklist, path, digest, item, spec, report):
    if checklist.get("sha256") != digest or checklist.get("sha256") != item.get("current_sha256"):
        report.fail(f"run {run_id} is stale: it was made for sha256 {str(checklist.get('sha256'))[:12]}, the file is {digest[:12]} and the approved current is {str(item.get('current_sha256'))[:12]}; start a new gate run")
    nonce = str(checklist.get("nonce", ""))
    for entry in checklist.get("defects", []):
        if not isinstance(entry, dict):
            report.fail(f"run {run_id} is stale: checklist.json has a malformed entry; start a new gate run"); continue
        crops = entry.get("crops") or {}
        for crop in crops.values():
            cp = run_dir / str(crop.get("file", ""))
            if not cp.is_file() or sha256_file(cp) != crop.get("sha256"):
                report.fail(f"{entry.get('id')}: crop {crop.get('file')} was changed or removed after the run; start a new gate run")
        if not crops or not entry.get("crop_box"): continue
        try: fresh = render_crops(target_image(path, spec, entry), entry["id"], entry["crop_box"], nonce)
        except Exception: fresh = {}
        if any(sha256_bytes(fresh.get(sc, ("", b""))[1]) != cr["sha256"] for sc, cr in crops.items()):
            report.fail(f"run {run_id} is stale: the crops of {entry.get('id')} no longer match the file; start a new gate run")


def check_verdicts(run_dir, checklist, defects, report):
    pending = []
    by_id = {e["id"]: e for e in checklist.get("defects", []) if isinstance(e, dict) and "id" in e}
    path = run_dir / "verdicts.json"
    verdicts, problem = {}, None
    if path.is_file():
        try: data = read_json(path, "verdicts.json")
        except UsageError as exc: data, problem = None, str(exc)
        if data is not None:
            if data.get("run_id") != checklist["run_id"] or data.get("nonce") != checklist["nonce"]:
                problem = "verdicts.json belongs to another run (run_id/nonce mismatch); verdicts must be made for this run"
            elif not isinstance(data.get("verdicts"), dict): problem = "verdicts.json has no verdicts object"
            else: verdicts = data["verdicts"]
    if problem: report.fail(problem)
    for defect in defects:
        did = defect["id"]
        entry = by_id.get(did)
        if defect.get("status") == "wontfix":
            closing = next((h for h in reversed(defect.get("history") or []) if isinstance(h, dict) and h.get("status") == "wontfix"), {})
            quote = closing.get("quote")
            if quote: report.ok(f"{did} accepted by user (wontfix): {short(quote)}")
            else: report.fail(f"{did} is wontfix without the user's words; close it again with --quote")
            continue
        if entry is None: report.fail(f"{did} is not in run {checklist['run_id']} (added later); start a new gate run"); continue
        if entry.get("error") or not entry.get("crops"): report.fail(f"{did}: {entry.get('error') or 'no crops'}"); continue
        verdict = verdicts.get(did)
        crop_names = " and ".join(c["file"] for c in entry["crops"].values())
        if not isinstance(verdict, dict) or verdict.get("status") != "pass": pending.append((did, entry["crops"]["100"]["file"]))
        if not isinstance(verdict, dict): report.skip(f"{did}: no verdict yet; inspect {crop_names} in {run_dir}"); continue
        hashes = {c["sha256"] for c in entry["crops"].values()}
        ev = verdict.get("evidence")
        if verdict.get("crop_sha256") not in hashes:
            report.fail(f"{did}: verdict rejected, crop_sha256 does not match any crop of this run")
        elif not isinstance(ev, str) or len(ev.strip()) < MIN_EVIDENCE:
            report.fail(f"{did}: verdict rejected, evidence must describe what was seen (>= {MIN_EVIDENCE} chars)")
        elif verdict.get("reviewer") not in ("self", "independent"):
            report.fail(f"{did}: verdict rejected, reviewer must be self or independent")
        elif verdict.get("status") == "pass": report.ok(f"{did} pass ({verdict['reviewer']}): {short(ev.strip())}")
        elif verdict.get("status") == "fail": report.fail(f"{did} verdict fail: {short(ev.strip())}")
        elif verdict.get("status") == "uncertain": report.skip(f"{did} verdict uncertain: {short(ev.strip())}")
        else: report.fail(f"{did}: verdict rejected, status must be pass, fail or uncertain")
    return pending


def resolved_proof(store_root, path, spec, digest, defects, report):
    for defect in defects:
        if defect.get("status") != "resolved": continue
        did = defect["id"]
        if defect.get("reported_sha256") and defect["reported_sha256"] == digest:
            report.fail(f"{did} marked resolved but the deliverable file is unchanged since it was reported"); continue
        try:
            current = region_crop(target_image(path, spec, defect), defect["bbox"])
            same = bool(defect.get("region_hash")) and region_hash(current, [0, 0] + list(current.size)) == defect["region_hash"]
            share = None
            if not same and defect.get("reported_crop"):
                cp = store_root / defect["reported_crop"]
                if cp.is_file(): share = changed_share(open_image(cp), current)
        except UsageError: raise
        except Exception as exc: report.fail(f"{did}: cannot read its region to confirm the fix ({exc})"); continue
        if same: report.fail(f"{did} marked resolved but its pixels are unchanged since it was reported")
        elif share is not None and share < (MIN_CHANGED_REQUEST if defect.get("kind") == "scope" and defect.get("quote") else MIN_CHANGED):
            report.fail(f"{did} marked resolved but almost nothing changed in its box ({share:.1%} of pixels)")


def disappeared(store, name, defects):
    known = {d["id"] for d in defects}
    gone = set()
    for checklist_path in sorted((store.root / "gate").glob("*/checklist.json")):
        try: checklist = json.loads(checklist_path.read_text(encoding="utf-8"))
        except (OSError, ValueError): continue
        if isinstance(checklist, dict) and checklist.get("deliverable") == name:
            gone |= {e.get("id") for e in checklist.get("defects", []) if isinstance(e, dict)} - known
    return sorted(g for g in gone if isinstance(g, str))


def cmd_gate(args):
    store = open_store(args.project)
    name = args.deliverable
    item = store.deliverable(name)
    spec = item.get("spec") or {}
    path = Path(args.file).expanduser() if args.file else store.resolve(item.get("path", ""))
    if not path.is_file(): raise UsageError(f"deliverable file {path} does not exist")
    digest = sha256_file(path)
    report = Report()
    if digest != item.get("current_sha256"):
        report.fail(f"{path.name} is not the approved current file — run approve deliverable (file sha256 {digest[:12]}, approved {str(item.get('current_sha256'))[:12]})")
    else: report.ok(f"{path.name} is the approved current file (sha256 {digest[:12]})")
    spec_checks(path, spec, report)

    all_defects = store.defects()
    defects = [d for d in all_defects if d.get("deliverable") == name]
    for gone in disappeared(store, name, all_defects): report.fail(f"defect {gone} disappeared from defects.jsonl")
    for gap in id_gaps(all_defects): report.fail(f"{gap} missing from defects.jsonl (defects are never deleted, only closed)")

    if args.run:
        run_dir, checklist = load_run(store, args.run)
        if checklist.get("deliverable") != name: raise UsageError(f"run {args.run} is for deliverable {checklist.get('deliverable')!r}, not {name!r}")
        run_id = args.run
        check_run_integrity(store, run_id, run_dir, checklist, path, digest, item, spec, report)
    else: run_id, run_dir, checklist = new_run(store, name, path, digest, spec, defects)
    stale = any("is stale" in f or "not the approved current file" in f or "after the run" in f for f in report.failing)
    resolved_proof(store.root, path, spec, digest, defects, report)

    pending = check_verdicts(run_dir, checklist, defects, report)
    for defect in defects:
        if defect.get("status") == "open": report.fail(f"{defect['id']} is still open: {short(defect.get('note'))}")
    lessons = read_lessons()
    for defect in defects:
        if defect.get("needs_lesson") and not lesson_linked(lessons, store.root, defect["id"]):
            report.fail(f"{defect['id']} was reported after delivery and has no lesson: run lesson add --defect {defect['id']} "
                        "--mistake ... --cause ... --check ...")

    passed = report.passed()
    print(f"Gate: {name} ({store.relative(path)})")
    print(f"Run: {run_id} (crops and checklist in {run_dir})")
    print("\n".join(report.lines()))
    self_verified = is_self_verified(run_dir)
    if passed:
        gate_rec = {"deliverable": name, "sha256": digest, "run_id": run_id, "time": now()}
        if self_verified: gate_rec["self_verified"] = True
        store.state.setdefault("gates", {})[name] = gate_rec
        store.save()
        result_label = "Result: PASS (self-verified — not independently reviewed)" if self_verified else "Result: PASS"
        try: print(result_label)
        except UnicodeEncodeError: print("Result: PASS (self-verified - not independently reviewed)")
    else:
        print("Result: FAIL\nNext:")
        for line in next_steps(name, path, digest, item, defects, run_id, stale, pending): print(f"- {line}")
    return 0 if passed else 1


def next_steps(name, path, digest, item, defects, run_id, stale, pending):
    steps = []
    if digest != item.get("current_sha256"):
        steps.append(f"if {path.name} is the file the user should receive: {SCRIPT_HINT} approve deliverable --name {name} --file {shlex.quote(str(path))}; otherwise gate the approved file")
    for defect in defects:
        if defect.get("status") == "open":
            steps.append(f"fix {defect['id']} ({short(defect.get('note'))}), check it, then {SCRIPT_HINT} defect close --id {defect['id']} --status resolved --note \"what changed\" (or, only if the user accepts it: --status wontfix --quote \"the user's words\")")
    if stale:
        steps.append(f"start a new run after the steps above: {SCRIPT_HINT} gate --deliverable {name}")
        return steps
    for did, crop in pending:
        steps.append(f"open {crop} (the 200% crop only if unclear) of run {run_id}, then {SCRIPT_HINT} verdict --run {run_id} --id {did} --status pass|fail|uncertain --evidence \"what you saw\"")
    steps.append(f"then: {SCRIPT_HINT} gate --deliverable {name} --run {run_id} (spec or unchanged-pixel failures need a fixed file, a new approve deliverable, and a new run)")
    return steps


def cmd_verdict(args):
    store = open_store(args.project)
    run_dir, checklist = load_run(store, args.run)
    entry = next((e for e in checklist.get("defects", []) if isinstance(e, dict) and e.get("id") == args.id), None)
    if entry is None: raise UsageError(f"defect {args.id!r} is not in run {args.run}")
    crop = (entry.get("crops") or {}).get(args.crop)
    if not crop: raise UsageError(f"run {args.run} has no {args.crop}% crop for {args.id}")
    crop_path = run_dir / crop["file"]
    if not crop_path.is_file() or sha256_file(crop_path) != crop["sha256"]: raise UsageError(f"{crop_path} is missing or changed since the run; start a new gate run")
    evidence = text_arg(args.evidence, "--evidence")
    if len(evidence) < MIN_EVIDENCE: raise UsageError(f"--evidence must describe what you saw in the crop (>= {MIN_EVIDENCE} characters)")
    path = run_dir / "verdicts.json"
    data = {}
    if path.is_file():
        try: data = read_json(path, "verdicts.json")
        except UsageError: data = {}
    if data.get("run_id") != checklist["run_id"] or data.get("nonce") != checklist["nonce"]: data = {}
    data.update({"run_id": checklist["run_id"], "nonce": checklist["nonce"], "deliverable": checklist.get("deliverable")})
    data.setdefault("verdicts", {})[args.id] = {"status": args.status, "crop_sha256": crop["sha256"], "evidence": evidence, "reviewer": args.reviewer, "time": now()}
    atomic_write(path, dump_json(data))
    print(f"{args.id} {args.status} recorded in {path}")
    return 0


# ---------------------------------------------------------------- hooks

def last_message_from_transcript(path):
    with open(path, "rb") as handle:
        handle.seek(0, 2); size = handle.tell()
        handle.seek(max(0, size - (2 << 20)))
        lines = handle.read().decode("utf-8", "replace").splitlines()
    for line in reversed(lines):
        if len(line) > (1 << 20): continue
        try: entry = json.loads(line)
        except ValueError: continue
        if not isinstance(entry, dict): continue
        for candidate in (entry, entry.get("message"), entry.get("payload")):
            if not isinstance(candidate, dict): continue
            if candidate.get("role") != "assistant" and entry.get("type") != "assistant": continue
            content = candidate.get("content")
            if isinstance(content, str) and content.strip(): return content
            if isinstance(content, list):
                text = "\n".join(c["text"] for c in content if isinstance(c, dict) and isinstance(c.get("text"), str))
                if text.strip(): return text
    return ""


def store_fingerprint(store):
    try: defects = store.defects_path.read_bytes()
    except OSError: defects = b""
    current = sorted((n, str(i.get("current_sha256"))) for n, i in store.state["deliverables"].items() if isinstance(i, dict))
    return sha256_bytes(defects + json.dumps([current, store.state.get("gates")], sort_keys=True, default=str).encode("utf-8"))


def ungated(store):
    defects = store.defects()
    return [name for name in sorted(store.state["deliverables"]) if not gate_is_valid(store, name, defects)]


def block_once(root, payload, message, fingerprint, reason):
    key = sha256_bytes("\0".join((str(payload.get("session_id") or ""), str(payload.get("turn_id") or ""),
                                   unicodedata.normalize("NFC", message), fingerprint)).encode("utf-8"))
    marker_path = root / "stop-hook.json"
    try: marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError): marker = {}
    if isinstance(marker, dict) and marker.get("key") == key: return ""
    try: atomic_write(marker_path, dump_json({"key": key, "time": now()}))
    except OSError: pass
    return json.dumps({"decision": "block", "reason": reason})


def prune_session_pointers(sessions_dir, max_age_seconds=7 * 86400):
    try:
        cutoff = time.time() - max_age_seconds
        for item in sessions_dir.glob("*.json"):
            try:
                if item.is_file() and item.stat().st_mtime < cutoff: item.unlink(missing_ok=True)
            except (OSError, ValueError, TypeError): pass
    except (OSError, ValueError, TypeError): pass


def write_session_pointer(session_id, root, base):
    if not valid_session_id(session_id): return
    sessions_dir = user_home() / "sessions"
    try:
        sessions_dir.mkdir(parents=True, exist_ok=True)
        prune_session_pointers(sessions_dir)
        atomic_write(sessions_dir / f"{session_id}.json", dump_json({"store": str(root.resolve()), "cwd": str(base), "time": now()}))
    except (OSError, ValueError, TypeError): pass


def inside_nested_repo(start, root):
    """True when start sits in a git repo below the store's project folder: a separate project
    (for example plugin development inside a job folder), which the store must not police."""
    try: path = Path(start).expanduser().resolve()
    except (OSError, RuntimeError, ValueError): return False
    project = root.parent
    for folder in [path] + list(path.parents):
        if folder == project: return False
        if (folder / ".git").exists(): return True
    return False


def discover_hook_store(payload):
    """Return (store root, the folder it was found from), or (None, None)."""
    cwd = payload.get("cwd") if isinstance(payload, dict) and isinstance(payload.get("cwd"), str) else os.getcwd()
    root = find_store(cwd)
    if root is not None: return (None, None) if inside_nested_repo(cwd, root) else (root, cwd)
    proj_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if proj_dir:
        try:
            cand = find_store(proj_dir)
            if cand is not None: return (None, None) if inside_nested_repo(proj_dir, cand) else (cand, proj_dir)
        except (OSError, RuntimeError): pass
    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    if valid_session_id(session_id):
        try:
            ptr_file = user_home() / "sessions" / f"{session_id}.json"
            if ptr_file.is_file():
                data = json.loads(ptr_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    store_val, base = data.get("store"), data.get("cwd")
                    # Pointers written before 2.4.1 have no "cwd" and may come from a plugin-development
                    # session; ignore them (the next session start writes a new one).
                    if isinstance(store_val, str) and store_val and isinstance(base, str) and base:
                        cand = Path(store_val)
                        if (cand.name == STORE_DIR and (cand / "state.json").is_file()
                                and not inside_nested_repo(base, cand)): return cand, base
        except (OSError, ValueError, TypeError): pass
    return None, None


def hook_stop(payload):
    if not isinstance(payload, dict) or payload.get("stop_hook_active") is True: return ""
    root, _ = discover_hook_store(payload)
    if root is None: return ""
    message = payload.get("last_assistant_message")
    if not isinstance(message, str):
        tr = payload.get("transcript_path")
        message = last_message_from_transcript(tr) if isinstance(tr, str) and tr else ""
    if not message.strip() or admits_unfinished(message) or not claims_completion(message):
        return ""
    try:
        store = Store(root)
        missing = ungated(store)
        open_defects = [d for d in store.defects() if d.get("status") == "open"]
        fingerprint = store_fingerprint(store)
    except UsageError as exc:
        reason = (f"image-studio: project store is corrupt: {exc}. Repair or restore {root} (state.json, "
                  "defects.jsonl) before claiming anything; meanwhile tell the user plainly that the work is not verified.")
        return block_once(root, payload, message, "corrupt:" + str(exc), reason)

    if not (missing or open_defects): return ""

    problems = [f"{short(d.get('note', ''), limit=80)} ({d.get('id')})" for d in open_defects]
    problems += [f"{name} has not passed the final check" for name in missing if name not in {d.get('deliverable') for d in open_defects}]
    reason = ("image-studio: you said the work is done, but it is not yet: " + "; ".join(problems) + ". "
              "Tell the user in their language and plain words what is still wrong (defect IDs only in parentheses) "
              "and ask whether to fix it, regenerate, or accept it; or run the gate to a pass: "
              f"{SCRIPT_HINT} gate --deliverable NAME")
    return block_once(root, payload, message, fingerprint, reason)


def hook_session_start(payload):
    root, base = discover_hook_store(payload) if isinstance(payload, dict) else (None, None)
    if root is None: return ""
    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    write_session_pointer(session_id, root, base)
    try: card = format_session_start_card(Store(root))
    except UsageError as exc: return f"image-studio: project store is corrupt: {exc}"
    try: size = Path(str(payload.get("transcript_path") or "")).stat().st_size
    except (OSError, ValueError): size = 0
    if size > LONG_CHAT_BYTES:
        card += (f"\nThis chat is long ({size >> 20} MB of history, resent on every step). For a new image job, "
                 "suggest the user start a new chat: this store, lessons, and taste carry the memory.")
    return card


def run_hook(argv):
    sys.stderr = io.StringIO()
    try:
        mode = argv[0] if argv else ""
        raw = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
        try: payload = json.loads(raw) if raw.strip() else {}
        except ValueError: payload = None
        out = hook_stop(payload) if (mode == "stop" and payload is not None) else (hook_session_start(payload or {}) if mode == "session-start" else "")
        if out: sys.stdout.write(out + "\n"); sys.stdout.flush()
    except BaseException: pass
    return 0


# ---------------------------------------------------------------- CLI

# ---------------------------------------------------------------- defect map and edit check

def changed_mask(before, after):
    """255 where any channel differs by more than CHANGE_LEVEL."""
    P = pil()
    bands = P.ImageChops.difference(before.convert("RGBA"), after.convert("RGBA")).split()
    peak = bands[0]
    for band in bands[1:]: peak = P.ImageChops.lighter(peak, band)
    return peak.point(lambda v: 255 if v > CHANGE_LEVEL else 0)


def outline(draw, box, color, width):
    x0, y0, x1, y1 = box
    for i in range(width):
        draw.rectangle((x0 + i, y0 + i, x1 - 1 - i, y1 - 1 - i), outline=color)


def cmd_map(args):
    P = pil()
    store = open_store(args.project)
    item = store.deliverable(args.deliverable)
    path = existing_file(args.file, "--file") if args.file else store.resolve(item.get("path", ""))
    if item.get("spec", {}).get("format") == "ZIP": raise UsageError("map works on a single image, not a ZIP")
    image = open_image(path).convert("RGB")
    spec = item.get("spec") or {}
    if (spec.get("width"), spec.get("height")) != (None, None) and image.size != (spec.get("width"), spec.get("height")):
        raise UsageError(f"{path.name} is {image.size[0]}x{image.size[1]}; the deliverable size is "
                         f"{spec.get('width')}x{spec.get('height')}")
    open_items = [d for d in store.defects() if d.get("deliverable") == args.deliverable and d.get("status") == "open"]
    draw = P.ImageDraw.Draw(image)
    width = max(2, round(min(image.size) / 300))
    for d in open_items:
        box = d["bbox"]
        outline(draw, box, (255, 0, 0), width)
        label = str(d["id"])
        tx, ty = box[0] + width, box[1] + width
        left, top, right, bottom = draw.textbbox((tx, ty), label)
        draw.rectangle((left - 1, top - 1, right + 1, bottom + 1), fill=(255, 0, 0))
        draw.text((tx, ty), label, fill=(255, 255, 255))
    out = Path(args.out)
    image.save(out, "PNG")
    print(f"Map: {out} ({len(open_items)} open defects on {path.name})")
    for d in open_items: print(defect_line(d))
    return 0


def cmd_edit_check(args):
    before_path, after_path = existing_file(args.before, "--before"), existing_file(args.after, "--after")
    before, after = open_image(before_path), open_image(after_path)
    if before.size != after.size:
        raise UsageError(f"size differs: {before.size[0]}x{before.size[1]} vs {after.size[0]}x{after.size[1]}")
    box = parse_bbox(args.bbox)
    w, h = before.size
    if box[2] > w or box[3] > h: raise UsageError(f"--bbox {box} is outside the image size {w}x{h}")
    if args.ring < 0: raise UsageError("--ring must be 0 or more")
    P = pil()
    changed = changed_mask(before, after)
    inside = P.Image.new("L", before.size, 0)
    inside.paste(255, tuple(box))
    outside = P.ImageChops.darker(changed, P.ImageChops.invert(inside))
    count_out, span = count_on(outside), outside.getbbox()
    print(f"Changed pixels inside the box: {count_on(P.ImageChops.darker(changed, inside))}")
    print(f"Changed pixels outside the box: {count_out}" + (f" (span {','.join(map(str, span))})" if span else ""))
    r = args.ring
    view = (max(0, box[0] - r), max(0, box[1] - r), min(w, box[2] + r), min(h, box[3] + r))
    panels = [before.crop(view).convert("RGB"), after.crop(view).convert("RGB"), changed.crop(view).convert("RGB")]
    vw, vh = view[2] - view[0], view[3] - view[1]
    sheet = P.Image.new("RGB", (vw * 3, vh))
    for i, panel in enumerate(panels): sheet.paste(panel, (i * vw, 0))
    draw = P.ImageDraw.Draw(sheet)
    local = (box[0] - view[0], box[1] - view[1], box[2] - view[0], box[3] - view[1])
    for i in (1, 2): outline(draw, (local[0] + i * vw, local[1], local[2] + i * vw, local[3]), (255, 0, 0), 1)
    sheet.save(args.out, "PNG")
    print(f"View: {args.out} (before | after | changed pixels, box + {r} px ring, 100%). Look at the ring for "
          "leftover fragments, seams, and halos.")
    return 1 if count_out else 0


EPILOG = """\
subcommands:
  init --project PATH --brand ID         example: python3 studio_state.py init --project . --brand acme
  approve deliverable --name N --file F [--width W --height H --format PNG|JPEG|WEBP|ZIP] [--alpha required|forbidden|any] [--quote T]
                                         example: python3 studio_state.py approve deliverable --name poster --file poster.png --width 1200 --height 800 --format PNG
  defect add --deliverable N --bbox x0,y0,x1,y1 --kind logo|seam|artifact|scope|color|other --note T [--source user|agent] [--quote T]
                                         example: python3 studio_state.py defect add --deliverable poster --bbox 100,50,200,150 --kind seam --note "visible seam"
  defect close --id D1 --status resolved|wontfix --note T [--quote T]
                                         example: python3 studio_state.py defect close --id D1 --status resolved --note "feathered seam"
  brief [--max-lines 40]                 example: python3 studio_state.py brief
  gate --deliverable N [--file F] [--run RUN]
                                         example: python3 studio_state.py gate --deliverable poster
  verdict --run RUN --id D1 --status pass|fail|uncertain --evidence T [--reviewer self|independent] [--crop 100|200]
                                         example: python3 studio_state.py verdict --run 20261018T000000Z-abc --id D1 --status pass --evidence "seam gone at 100%"
  pref add [--brand B] --rule T --check T [--evidence T] [--confirmed]
                                         example: python3 studio_state.py pref add --brand acme --rule "No bevels" --check "inspect edges" --confirmed
  lesson add --mistake T --cause T --check T [--worked T] [--defect D1] [--kind K] [--brand B]
                                         example: python3 studio_state.py lesson add --defect D4 --mistake "delivered a soft poster" --cause "upscaled a generated patch" --check "compare at 100% before delivery"
  lesson list [--brand B]                example: python3 studio_state.py lesson list --brand acme
  taste add --note T [--aspect color|line|composition|detail|lighting|text|style|other] [--quote T] [--deliverable N] [--brand B]
                                         example: python3 studio_state.py taste add --aspect color --note "deep blue night palette with warm gold accents" --quote "love this palette"
  taste list [--brand B]                 example: python3 studio_state.py taste list --brand acme
  brand set --brand B [--color NAME=#RRGGBB[:role]] [--font ROLE=Family] [--logo FILE] [--ref FILE=role] [--do T] [--dont T] [--remove KEY]
                                         example: python3 studio_state.py brand set --brand acme --color gold=#E1C178:accent --font title=Cinzel --logo logo.png --ref style.png=style --dont "no 3D render look"
  brand show [--brand B]                 example: python3 studio_state.py brand show --brand acme
  map --deliverable N [--file F] --out F  draw every open defect on one image for the user to confirm at once
                                         example: python3 studio_state.py map --deliverable poster --out defect-map.png
  edit-check --before A --after B --bbox x0,y0,x1,y1 [--ring 24] [--out F]
                                         changed pixels outside the edit box (exit 1 if any) and one before|after|changes view
                                         example: python3 studio_state.py edit-check --before v7.png --after v8.png --bbox 280,320,370,410
  hook session-start | hook stop         example: python3 studio_state.py hook session-start < payload.json

approve, defect, brief, gate and verdict find the store by walking up from --project or the current folder.
init creates it; pref add does not use the project store; lessons (lessons.jsonl) and taste notes (brands/<brand>/taste.jsonl, taste.jsonl) live in ${IMAGE_STUDIO_HOME:-~/.image-studio}, shared by every job; hooks use the cwd from the hook input.
exit codes: 0 ok / gate pass, 1 gate fail or edit-check found changes outside the box, 2 bad input or no store
"""


def build_parser():
    parser = argparse.ArgumentParser(prog="studio_state.py", description=__doc__.split("\n\n")[0],
                                     epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    p = sub.add_parser("init")
    p.add_argument("--project", required=True); p.add_argument("--brand", required=True)
    p.set_defaults(func=cmd_init)

    approve = sub.add_parser("approve").add_subparsers(dest="what", metavar="deliverable", required=True)
    p = approve.add_parser("deliverable", parents=[common])
    p.add_argument("--name", required=True); p.add_argument("--file", required=True)
    p.add_argument("--width", type=int); p.add_argument("--height", type=int)
    p.add_argument("--format"); p.add_argument("--alpha", choices=ALPHA_RULES); p.add_argument("--quote")
    p.set_defaults(func=cmd_approve_deliverable)

    defect = sub.add_parser("defect").add_subparsers(dest="what", metavar="add|close", required=True)
    p = defect.add_parser("add", parents=[common])
    p.add_argument("--deliverable", required=True); p.add_argument("--bbox", required=True, nargs="+")
    p.add_argument("--kind", required=True, choices=KINDS); p.add_argument("--note", required=True)
    p.add_argument("--source", choices=("user", "agent"), default="user"); p.add_argument("--quote")
    p.set_defaults(func=cmd_defect_add)

    p = defect.add_parser("close", parents=[common])
    p.add_argument("--id", required=True); p.add_argument("--status", required=True, choices=("resolved", "wontfix"))
    p.add_argument("--note", required=True); p.add_argument("--quote")
    p.set_defaults(func=cmd_defect_close)

    p = sub.add_parser("brief", parents=[common])
    p.add_argument("--max-lines", type=int, default=40)
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("gate", parents=[common])
    p.add_argument("--deliverable", required=True); p.add_argument("--file"); p.add_argument("--run")
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser("verdict", parents=[common])
    p.add_argument("--run", required=True); p.add_argument("--id", required=True)
    p.add_argument("--status", required=True, choices=("pass", "fail", "uncertain"))
    p.add_argument("--evidence", required=True); p.add_argument("--reviewer", choices=("self", "independent"), default="self")
    p.add_argument("--crop", choices=("100", "200"), default="100")
    p.set_defaults(func=cmd_verdict)

    p = sub.add_parser("map", parents=[common])
    p.add_argument("--deliverable", required=True); p.add_argument("--file"); p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_map)

    p = sub.add_parser("edit-check")
    p.add_argument("--before", required=True); p.add_argument("--after", required=True)
    p.add_argument("--bbox", required=True, nargs="+"); p.add_argument("--ring", type=int, default=24)
    p.add_argument("--out", default="edit-check.png")
    p.set_defaults(func=cmd_edit_check)

    pref = sub.add_parser("pref").add_subparsers(dest="what", metavar="add", required=True)
    p = pref.add_parser("add")
    p.add_argument("--brand"); p.add_argument("--rule", required=True); p.add_argument("--check", required=True)
    p.add_argument("--evidence"); p.add_argument("--confirmed", action="store_true")
    p.set_defaults(func=cmd_pref_add)

    lesson = sub.add_parser("lesson").add_subparsers(dest="what", metavar="add|list", required=True)
    p = lesson.add_parser("add", parents=[common])
    p.add_argument("--mistake", required=True); p.add_argument("--cause", required=True); p.add_argument("--check", required=True)
    p.add_argument("--defect"); p.add_argument("--kind", choices=KINDS); p.add_argument("--brand"); p.add_argument("--worked")
    p.set_defaults(func=cmd_lesson_add)
    p = lesson.add_parser("list")
    p.add_argument("--brand")
    p.set_defaults(func=cmd_lesson_list)

    taste = sub.add_parser("taste").add_subparsers(dest="what", metavar="add|list", required=True)
    p = taste.add_parser("add", parents=[common])
    p.add_argument("--note", required=True); p.add_argument("--aspect", choices=ASPECTS, default="other")
    p.add_argument("--quote"); p.add_argument("--deliverable"); p.add_argument("--brand")
    p.set_defaults(func=cmd_taste_add)
    p = taste.add_parser("list")
    p.add_argument("--brand")
    p.set_defaults(func=cmd_taste_list)

    brand_p = sub.add_parser("brand").add_subparsers(dest="what", metavar="set|show", required=True)
    p = brand_p.add_parser("set")
    p.add_argument("--brand", required=True)
    p.add_argument("--color", action="append", help="NAME=#RRGGBB[:role]"); p.add_argument("--font", action="append", help="ROLE=Family")
    p.add_argument("--logo"); p.add_argument("--ref", action="append", help="FILE=role")
    p.add_argument("--do", action="append"); p.add_argument("--dont", action="append")
    p.add_argument("--remove", action="append", help="colors:NAME, fonts:ROLE, refs:FILE, do:TEXT, dont:TEXT, or logo")
    p.set_defaults(func=cmd_brand_set)
    p = brand_p.add_parser("show", parents=[common])
    p.add_argument("--brand")
    p.set_defaults(func=cmd_brand_show)

    p = sub.add_parser("hook")
    p.add_argument("mode", choices=("session-start", "stop"))
    return parser


def store_lock(args):
    """Serialize commands that rewrite one store, so parallel agents do not overwrite each other's defects or verdicts."""
    if fcntl is None or getattr(args, "command", None) not in ("approve", "defect", "gate", "verdict"): return None
    try:
        root = find_store(getattr(args, "project", None) or os.getcwd())
        if root is None: return None
        handle = open(root / ".lock", "a")
        fcntl.flock(handle, fcntl.LOCK_EX)
        return handle
    except OSError: return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["hook"]: return run_hook(argv[1:])
    args = build_parser().parse_args(argv)
    lock = store_lock(args)
    try: return args.func(args)
    except UsageError as exc: print(f"error: {exc}", file=sys.stderr)
    except OSError as exc: print(f"error: {exc}", file=sys.stderr)
    except Exception as exc: print(f"error: unexpected {exc.__class__.__name__}: {exc}", file=sys.stderr)
    finally:
        if lock is not None: lock.close()
    return 2


if __name__ == "__main__":
    sys.exit(main())
