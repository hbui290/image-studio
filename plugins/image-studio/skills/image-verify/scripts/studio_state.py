#!/usr/bin/env python3
"""Project memory and evidence gate for image-studio.

Keeps a per-project store in `<project>/.image-studio/` (approved deliverables,
user decisions, every defect ever reported, and construction rules) and a bounded user preference
file in `${IMAGE_STUDIO_HOME:-~/.image-studio}`. The `gate` subcommand is the only way
to prove a deliverable is done: the file must be the approved one, match its spec,
every resolved defect must show changed pixels, and every recorded defect needs
a verdict that names a crop made in the same gate run.
`hook session-start` and `hook stop` are thin wrappers for Claude Code and Codex plugin
hooks; they always exit 0 and print nothing on errors.

Exit codes: 0 success or gate pass, 1 gate fail, edit-check found changes outside the box or mask
(or a mask with no effect), axis-check found a bend, blend wrote a color-mismatched result, shape-check found a
changed silhouette, crop-check found a crop or size problem, align-check --auto found no reliable match or a scale to
fix, or mask-from-diff found no change, 2 bad input or missing store.
numpy and OpenCV are optional (see accel.py); --engine pillow|fast or IMAGE_STUDIO_ENGINE picks the engine.
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

if str(Path(__file__).resolve().parent) not in sys.path: sys.path.insert(0, str(Path(__file__).resolve().parent))
try: import accel  # optional numpy/OpenCV engine (sibling file); imports nothing heavy until a command selects it
except ImportError: accel = None  # studio_state.py copied alone: Pillow only


def fast():
    """True when the running command selected the numpy/OpenCV engine."""
    return accel is not None and accel.fast()

STORE_DIR = ".image-studio"
SCHEMA_VERSION = 1
PREF_CAP = 1500
CROP_MARGIN = 16
MIN_EVIDENCE = 10
NOTE_LIMIT = 120
MIN_BOX = 16           # smallest defect box side (px) without a user quote
MIN_BOX_SHARE = 0.001  # smallest defect box area (share of the image) without a user quote
WIDE_BOX_SHARE = 0.25  # largest agent defect box (share of the image) without --wide
CHANGE_LEVEL = 8       # per-channel difference that counts as a changed pixel
REAL_CHANGE_LEVEL = 12  # edit-check --mask: per-channel difference that counts as a real (not encoder noise) change
MASK_OUTSIDE_LIMIT = 0.001  # edit-check --mask: share of outside pixels allowed a real change (re-encode noise)
MASK_EFFECT_MIN = 0.005     # edit-check --mask: below this share of changed mask pixels the mask did nothing or is inverted
DE_SAMPLES = 5000      # blend: most ring pixels sampled for CIEDE2000
DE_MEAN_LIMIT, DE_P95_LIMIT = 2.0, 3.5  # blend: ring color difference (CIEDE2000) above either is a color mismatch
ALIGN_ASPECT_LIMIT = 0.01   # align-check: largest relative aspect difference between patch and target area
ENGINES = ("auto", "pillow", "fast")  # --engine on accelerated commands (see accel.py)
AUTO_SCALES = tuple(round(0.90 + 0.02 * i, 2) for i in range(11))  # align-check --auto: patch scales tried, 0.90-1.10
AUTO_MIN_SCORE = 0.8   # align-check --auto: below this TM_CCOEFF_NORMED score there is no reliable match
AUTO_FLAT_STD = 2.0    # align-check --auto: a template whose channels vary less than this (std, 0-255) is flat
AUTO_TIE = 0.01        # align-check --auto: another place scoring within this of the best makes the match ambiguous
AUTO_SCALE_LIMIT = 0.01  # align-check --auto: a best scale further than this from 1 means the patch must be resized
SHAPE_IOU_LOSS = 0.01  # shape-check: largest allowed 1 - IoU between the before and after silhouettes
SHAPE_ASPECT = 0.01    # shape-check: largest relative change of the silhouette box w/h
SHAPE_EDGE_CAP = 512   # shape-check: farthest boundary search (px); beyond it the offset reads "over 512 px"
SHAPE_EDGE_SHARE = 0.001  # shape-check: default boundary offset limit, share of the long side (at least 2 px)
CROP_RATIOS = ((16, 9), (4, 5), (1, 1), (9, 16))  # crop-check: common feed and banner ratios
CROP_DISPLAY_FACTOR = 2  # crop-check --display: the image must be this many times the display size (high-DPI screens)
ASPECT_LIMIT = 0.025   # gate: largest absolute w/h difference that a resize keeping aspect can fix
FILE_BUDGET = 1000000  # gate: PNG/JPEG/WebP deliverables above this many bytes get a warning
CARD_LIMIT = 2400
LESSONS_SHOWN = 5      # lessons printed in the session card and brief
TASTE_SHOWN = 6        # taste notes printed in the session card and brief
CONSTRUCTION_SHOWN = 3  # construction rules printed in the session card and brief
REPEAT_IOU = 0.1       # defect add: a user box this close to an earlier one (or centered in it) is a repeat (bench/score.py's rule)
REPEAT_INSIDE = 0.6    # defect add: ... or this share of the earlier box lies inside the new one (a wider box around it)
REPEAT_ASPECT = 0.02   # defect add: images whose w/h differ by at most this share are copies of one artwork (compared as fractions)
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
def count_on(mask):
    if fast(): return int(accel.modules()[0].count_nonzero(accel.to_array(mask) == 255))
    return mask.histogram()[255]
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
        self.construction_path = self.root / "construction.jsonl"
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

    def constructions(self):
        if not self.construction_path.exists(): return []
        items = []
        for n, line in enumerate(self.construction_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip(): continue
            try: item = json.loads(line)
            except ValueError: raise UsageError(f"{self.construction_path}:{n}: not valid JSON") from None
            if not isinstance(item, dict) or not isinstance(item.get("defect"), str):
                raise UsageError(f"{self.construction_path}:{n}: construction record must be an object with a defect")
            items.append(item)
        return items

    def save_constructions(self, items):
        atomic_write(self.construction_path, "".join(json.dumps(i, sort_keys=True, ensure_ascii=False) + "\n" for i in items))

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
    sw, sh = spec.get("width"), spec.get("height")
    if img.size != (sw, sh):
        text = f"{label}: size {img.size[0]}x{img.size[1]}, spec {sw}x{sh}"
        if isinstance(sw, int) and isinstance(sh, int) and sh > 0 and img.size[1] > 0:
            got, want = img.size[0] / img.size[1], sw / sh
            if abs(got - want) > ASPECT_LIMIT:
                text += f"; aspect {got:.3f} vs spec {want:.3f} (more than {ASPECT_LIMIT} apart: crop or pad, never stretch)"
            else: text += f"; same aspect within {ASPECT_LIMIT} (a resize keeping aspect fits)"
        problems.append(text)
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


def parse_bbox(values, label="--bbox"):
    raw = values[0].split(",") if len(values) == 1 else values
    try: box = [int(str(v).strip()) for v in raw]
    except ValueError: raise UsageError(f"{label} must be 4 integers: x0,y0,x1,y1") from None
    if len(box) != 4 or box[0] < 0 or box[1] < 0 or box[2] <= box[0] or box[3] <= box[1]:
        raise UsageError(f"{label} needs 0 <= x0 < x1 and 0 <= y0 < y1 (x1, y1 exclusive)")
    return box


def same_region(new, old):
    """bench/score.py's hit rule (IoU >= 0.1, or the new box's center inside the old box), plus an old box lying
    mostly inside a wider new box. Boxes may be fractions of the image."""
    w, h = min(new[2], old[2]) - max(new[0], old[0]), min(new[3], old[3]) - max(new[1], old[1])
    inter = w * h if w > 0 and h > 0 else 0
    old_area = (old[2] - old[0]) * (old[3] - old[1])
    union = (new[2] - new[0]) * (new[3] - new[1]) + old_area - inter
    cx, cy = (new[0] + new[2]) / 2, (new[1] + new[3]) / 2
    return ((union > 0 and inter / union >= REPEAT_IOU) or (old[0] <= cx <= old[2] and old[1] <= cy <= old[3])
            or (old_area > 0 and inter / old_area >= REPEAT_INSIDE))


def defect_size(store, d):
    """The image size a defect was reported on; older records fall back to their deliverable's current spec."""
    size = d.get("image_size")
    if not isinstance(size, list) or len(size) != 2:
        spec = (store.state["deliverables"].get(d.get("deliverable")) or {}).get("spec") or {}
        size = [spec.get("width"), spec.get("height")]
    return size if all(isinstance(v, int) and v > 0 for v in size) else None


def repeated(store, size, box, defects):
    """IDs of earlier user complaints (any status) on the same region of the same artwork: the same size, or a copy
    whose aspect is within 2% (an upscale or a small crop), compared as fractions of the image. Agent findings and
    scope requests with the user's words are not complaints."""
    w, h = size
    new = [box[0] / w, box[1] / h, box[2] / w, box[3] / h]
    out = []
    for d in defects:
        if d.get("source") == "agent" or (d.get("kind") == "scope" and d.get("quote")): continue
        old, old_size = d.get("bbox"), defect_size(store, d)
        if old_size is None or not isinstance(old, list) or len(old) != 4 or not all(isinstance(v, int) for v in old): continue
        ow, oh = old_size
        if abs(ow / oh - w / h) > REPEAT_ASPECT * (w / h): continue
        if same_region(new, [old[0] / ow, old[1] / oh, old[2] / ow, old[3] / oh]): out.append(d["id"])
    return out


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
        record["image_size"] = [image.size[0], image.size[1]]
        reported = region_crop(image, box)
    except UsageError: raise
    except Exception as exc: raise UsageError(f"cannot read the defect region from {path.name}: {exc}") from None
    width, height = box[2] - box[0], box[3] - box[1]
    small = width < MIN_BOX or height < MIN_BOX or width * height < MIN_BOX_SHARE * image.size[0] * image.size[1]
    if small and not quote:
        raise UsageError(f"--bbox {width}x{height} is too small to prove a fix (needs >= {MIN_BOX}x{MIN_BOX} px and "
                         f">= {MIN_BOX_SHARE:.1%} of the image); draw a larger box or pass --quote with the user's words")
    if args.wide and args.source != "agent": raise UsageError("--wide is only for --source agent")
    seen = (min(box[2], image.size[0]) - box[0]) * (min(box[3], image.size[1]) - box[1])
    if args.source == "agent" and seen > WIDE_BOX_SHARE * image.size[0] * image.size[1] and not args.wide:
        raise UsageError(f"--bbox covers {seen / (image.size[0] * image.size[1]):.0%} of the image; an agent box over "
                         f"{WIDE_BOX_SHARE:.0%} has not located the defect: re-check the crop and draw a tighter box, or pass "
                         "--wide for a whole-image problem (overall softness, color cast)")
    if args.wide: record["wide"] = True
    if quote: record["quote"] = quote
    defects = store.defects()
    # A requested change (kind scope with the user's words: new text, a removed element) is not a miss, so it needs no lesson.
    request = args.kind == "scope" and bool(quote)
    after_delivery = args.source == "user" and not request and gate_is_valid(store, args.deliverable, defects)
    if after_delivery: record["needs_lesson"] = True
    # The user pointing at a region again means patching strokes failed: work out how the object is built.
    repeat = repeated(store, image.size, box, defects) if args.source == "user" and not request else []
    if repeat: record.update(repeat_of=repeat, needs_construction=True, needs_lesson=True)
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
    lesson_cmd = f"{SCRIPT_HINT} lesson add --defect {record['id']} --mistake \"...\" --cause \"...\" --check \"...\""
    if repeat:
        print(f"Repeat: this region was already reported ({', '.join(repeat)}). Stop patching single strokes. "
              "Follow image-verify/references/construction-reference.md: state how the object is built, find real reference "
              "photos of the same action, confirm them with the user, then rebuild the whole part from that rule. Record it:\n"
              f"{SCRIPT_HINT} construction add --defect {record['id']} --object \"...\" --rule \"...\" --ref FILE   "
              "(or --quote \"the user's words explaining it\")")
        print(f"The user pointed at the same region again, so this is a miss. Record what to do differently:\n{lesson_cmd}")
    if after_delivery:
        print(f"{args.deliverable} had passed the gate, so this is a miss after delivery. Record what to do differently"
              + (" (the lesson above covers it)." if repeat else f":\n{lesson_cmd}"))
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
    def tasks(items):
        return {l.get("project") for l in items if l.get("brand") == record.get("brand") and l.get("kind") == record["kind"] and l.get("project")}
    brand_prefs = read_prefs(pref_paths(record.get("brand"))[0]) if record.get("brand") else []
    covered = any(check.lower() in rule.lower() for _, rule in brand_prefs)
    if record["kind"] != "other" and not covered and len(tasks(lessons)) < 2 <= len(tasks(lessons + [record])):
        brand = f" --brand {record['brand']}" if record.get("brand") else ""
        print(f"This kind of mistake ({record['kind']}) has now happened in 2 tasks. Ask the user whether to make it a rule:\n"
              f"{SCRIPT_HINT} pref add{brand} --rule \"...\" --check \"{short(check, 200)}\"   (add --confirmed only after the user agrees)")
    return 0


def cmd_lesson_list(args):
    lessons = [l for l in read_lessons() if args.brand is None or l.get("brand") == args.brand]
    if not lessons: print("No lessons recorded."); return 0
    for item in lessons: print(lesson_line(item) + f" (cause: {short(item.get('cause', ''), 90)})")
    return 0


# ---------------------------------------------------------------- construction rules

def construction_line(item, limit=110):
    basis = [f"{len(item['refs'])} ref" + ("s" if len(item["refs"]) > 1 else "")] if isinstance(item.get("refs"), list) and item["refs"] else []
    if isinstance(item.get("quote"), str): basis.append(f'user: "{short(item["quote"], 60)}"')
    return f"- {item.get('defect')} {short(item.get('object'), 40)}: {short(item.get('rule'), limit)}" + (f" ({'; '.join(basis)})" if basis else "")


def construction_linked(constructions, defect_id):
    return any(c.get("defect") == defect_id for c in constructions)


def cmd_construction_add(args):
    store = open_store(args.project)
    obj, rule = text_arg(args.object, "--object"), text_arg(args.rule, "--rule")
    quote = text_arg(args.quote, "--quote", False)
    defect = next((d for d in store.defects() if d.get("id") == args.defect), None)
    if defect is None: raise UsageError(f"unknown defect id {args.defect!r}")
    if not args.ref and not quote:
        raise UsageError("construction add needs at least one --ref FILE (a real reference photo of the same action) "
                         "or --quote with the user's own words explaining how it is built")
    refs = []
    for value in args.ref or []:
        path = existing_file(value, "--ref")
        try:
            with pil().Image.open(path) as img: img.verify()
        except UsageError: raise
        except Exception as exc: raise UsageError(f"--ref {value} is not a readable image ({exc})") from None
        refs.append({"path": store.relative(path), "sha256": sha256_file(path)})
    record = {"defect": args.defect, "deliverable": defect.get("deliverable"), "object": obj, "rule": rule, "refs": refs, "time": now()}
    if quote: record["quote"] = quote
    store.save_constructions(store.constructions() + [record])
    print(f"Recorded construction for {args.defect} ({obj}): {rule}")
    print("Rebuild the whole part from this rule, then check every clause of it on the final pixels before delivery.")
    return 0


def cmd_construction_list(args):
    items = open_store(args.project).constructions()
    if not items: print("No construction rules recorded."); return 0
    for item in items:
        refs = ", ".join(r.get("path", "") for r in item.get("refs") or [] if isinstance(r, dict))
        print(construction_line(item, 400) + f" {item.get('time', '')}" + (f"\n  refs: {refs}" if refs else ""))
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
    if any(d.get("needs_construction") for d in mine):
        try: constructions = store.constructions()
        except UsageError: return False
        if any(d.get("needs_construction") and not construction_linked(constructions, d["id"]) for d in mine): return False
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
    built = [construction_line(c) for c in store.constructions()[-CONSTRUCTION_SHOWN:][::-1]]
    return delivs, decs, prefs, conf, lessons, taste, built


BUILT_TITLE = "How these objects are built (rebuild from the rule, never patch single strokes):"


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
    delivs, decs, prefs, conf, lessons, taste, built = shared_sections(store, defects)
    prop = sum(1 for st, _ in prefs if st == "proposed")
    if prop: head.append(f"Preferences: {prop} proposed, ask the user to confirm (pref add ... --confirmed).")
    sections = [("Deliverables:", delivs), (BUILT_TITLE, built)]
    sections += [("Your taste (match it):", taste), ("Lessons from earlier tasks (check these):", lessons), ("Confirmed preferences:", conf), ("Recent decisions:", decs), ("Closed defects (resolved ones are re-checked by the gate):", [f"- {defect_line(d)}" for d in [d for d in defects if d.get("status") != "open"][::-1]])]
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
    delivs, decs, _, conf, lessons, taste, built = shared_sections(store, defects)

    for limit in (100, 80, 60, 40, 20, 10, 5, 0):
        lines = [f"image-studio project memory (brand: {state.get('brand')} | store: {store.root}):"]
        lines.append(f"Open defects ({len(open_items)}, all listed; gate cannot pass while any is open):" if open_items else "Open defects: none")
        lines.extend(f"- {defect_line(d, limit=limit)}" for d in open_items)
        if delivs: lines.append("Deliverables:"); lines.extend(delivs)
        if built: lines.append(BUILT_TITLE); lines.extend(built)
        if decs: lines.append("Recent decisions:"); lines.extend(decs)
        if taste: lines.append("Your taste (match it):"); lines.extend(taste)
        if lessons: lines.append("Lessons from earlier tasks (check these):"); lines.extend(lessons)
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
    size = path.stat().st_size
    if fmt in ("PNG", "JPEG", "WEBP") and size > FILE_BUDGET:
        report.ok(f"file size: warning, {size / 1e6:.1f} MB is over the {FILE_BUDGET // 1000000} MB budget for PNG/JPEG/WebP "
                  "(not a failure; compress it if it is for the web)")


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
            why = (f"repeats {', '.join(map(str, defect['repeat_of']))} (the user pointed at the same region again)"
                   if defect.get("repeat_of") else "was reported after delivery")
            report.fail(f"{defect['id']} {why} and has no lesson: run lesson add --defect {defect['id']} "
                        "--mistake ... --cause ... --check ...")
    constructions = store.constructions() if any(d.get("needs_construction") for d in defects) else []
    for defect in defects:
        if defect.get("needs_construction") and not construction_linked(constructions, defect["id"]):
            report.fail(f"{defect['id']} repeats {', '.join(map(str, defect.get('repeat_of') or []))} and has no construction rule: "
                        "research how the object is built (image-verify/references/construction-reference.md), then run "
                        f"construction add --defect {defect['id']} --object ... --rule ... --ref FILE (or --quote ...)")

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


def verdict_record(run_id, run_dir, checklist, defect_id, status, evidence, scale, reviewer):
    entry = next((e for e in checklist.get("defects", []) if isinstance(e, dict) and e.get("id") == defect_id), None)
    if entry is None: raise UsageError(f"defect {defect_id!r} is not in run {run_id}")
    if status not in ("pass", "fail", "uncertain"): raise UsageError(f"{defect_id}: status must be pass, fail, or uncertain")
    crop = (entry.get("crops") or {}).get(scale)
    if not crop: raise UsageError(f"run {run_id} has no {scale}% crop for {defect_id}")
    crop_path = run_dir / crop["file"]
    if not crop_path.is_file() or sha256_file(crop_path) != crop["sha256"]: raise UsageError(f"{crop_path} is missing or changed since the run; start a new gate run")
    evidence = text_arg(evidence, f"{defect_id} evidence")
    if len(evidence) < MIN_EVIDENCE: raise UsageError(f"{defect_id}: evidence must describe what you saw in the crop (>= {MIN_EVIDENCE} characters)")
    return {"status": status, "crop_sha256": crop["sha256"], "evidence": evidence, "reviewer": reviewer, "time": now()}


def cmd_verdict(args):
    store = open_store(args.project)
    run_dir, checklist = load_run(store, args.run)
    if args.from_file:
        if args.id or args.status or args.evidence: raise UsageError("use either --from or --id/--status/--evidence, not both")
        try: entries = json.loads(Path(args.from_file).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc: raise UsageError(f"cannot read --from {args.from_file}: {exc}") from None
        if not isinstance(entries, list) or not entries or not all(isinstance(e, dict) for e in entries):
            raise UsageError('--from must hold a non-empty list of {"id", "status", "evidence"} objects')
    elif args.id and args.status and args.evidence:
        entries = [{"id": args.id, "status": args.status, "evidence": args.evidence, "crop": args.crop}]
    else: raise UsageError("give --id, --status and --evidence, or --from FILE")
    records = {}
    for e in entries:  # validate every entry before writing any
        defect_id = str(e.get("id"))
        records[defect_id] = verdict_record(args.run, run_dir, checklist, defect_id, e.get("status"), e.get("evidence"),
                                            str(e.get("crop", args.crop)), args.reviewer)
    path = run_dir / "verdicts.json"
    data = {}
    if path.is_file():
        try: data = read_json(path, "verdicts.json")
        except UsageError: data = {}
    if data.get("run_id") != checklist["run_id"] or data.get("nonce") != checklist["nonce"]: data = {}
    data.update({"run_id": checklist["run_id"], "nonce": checklist["nonce"], "deliverable": checklist.get("deliverable")})
    data.setdefault("verdicts", {}).update(records)
    atomic_write(path, dump_json(data))
    if len(records) == 1 and not args.from_file: print(f"{args.id} {args.status} recorded in {path}")
    else: print(f"{len(records)} verdicts recorded in {path}: " + ", ".join(f"{k} {v['status']}" for k, v in records.items()))
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
    (for example plugin development inside a task folder), which the store must not police."""
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
        card += (f"\nThis chat is long ({size >> 20} MB of history, resent on every step). For a new image task, "
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

def changed_mask(before, after, level=CHANGE_LEVEL):
    """255 where any channel differs by more than level."""
    P = pil()
    if fast():
        np, cv2 = accel.modules()
        r, g, b, a = cv2.split(cv2.absdiff(np.asarray(before.convert("RGBA")), np.asarray(after.convert("RGBA"))))
        return P.Image.fromarray(cv2.threshold(cv2.max(cv2.max(r, g), cv2.max(b, a)), level, 255, cv2.THRESH_BINARY)[1])
    bands = P.ImageChops.difference(before.convert("RGBA"), after.convert("RGBA")).split()
    peak = bands[0]
    for band in bands[1:]: peak = P.ImageChops.lighter(peak, band)
    return peak.point(lambda v: 255 if v > level else 0)


def open_8bit(path, label):
    img = open_image(path)
    if img.mode in ("I", "F") or img.mode.startswith("I;"):
        raise UsageError(f"{label} is a 16-bit or float image ({img.mode}); save an 8-bit copy first")
    return img


def hard_mask(mask_img, size, label, against):
    """0/255 mask: pixels at 128 or brighter are in; transparent pixels are out. blend, edit-check and align-check share it."""
    P = pil()
    if mask_img.size != size:
        raise UsageError(f"{label} is {mask_img.size[0]}x{mask_img.size[1]}; it must match {against} {size[0]}x{size[1]}")
    if "transparency" in mask_img.info: mask_img = mask_img.convert("RGBA")  # P/RGB masks with a transparent color
    mask = mask_img.convert("L")
    if "A" in mask_img.getbands(): mask = P.ImageChops.darker(mask, mask_img.getchannel("A"))
    hard = mask.point(lambda v: 255 if v >= 128 else 0)
    if not hard.getbbox(): raise UsageError(f"{label} is empty (no pixel at 128 or brighter)")
    return hard


def grow(mask, px):
    """Dilate a 0/255 mask by px pixels (square), working only around its box."""
    P = pil()
    box = mask.getbbox()
    if not px or not box: return mask
    W, H = mask.size
    work = (max(0, box[0] - px), max(0, box[1] - px), min(W, box[2] + px), min(H, box[3] + px))
    part = mask.crop(work)
    if fast():
        part = P.Image.fromarray(accel.modules()[1].dilate(accel.to_array(part), accel.square(px)))
    else:
        for _ in range(px // 2): part = part.filter(P.ImageFilter.MaxFilter(5))
        if px % 2: part = part.filter(P.ImageFilter.MaxFilter(3))
    out = mask.copy(); out.paste(part, work[:2])
    return out


def parse_at(value, label="--at"):
    try: x, y = (int(v) for v in value.split(","))
    except ValueError: raise UsageError(f"{label} takes x,y, got {value!r}") from None
    return x, y


def on_indices(mask, limit):
    """Indices of the mask's on pixels, evenly thinned to at most limit."""
    if fast():
        idx = accel.modules()[0].flatnonzero(accel.to_array(mask))
        return idx[::max(1, -(-len(idx) // limit))]
    idx = [i for i, v in enumerate(mask.tobytes()) if v]
    return idx[::max(1, -(-len(idx) // limit))]


_LINEAR = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (v / 255 for v in range(256))]


def srgb_to_lab(rgb):
    """8-bit sRGB to CIELAB, D65 white."""
    r, g, b = (_LINEAR[c] for c in rgb)
    xyz = ((0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047,
           0.2126729 * r + 0.7151522 * g + 0.0721750 * b,
           (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883)
    fx, fy, fz = (t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116 for t in xyz)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def ciede2000(lab1, lab2):
    """CIEDE2000 color difference (Sharma, Wu and Dalal 2005), kL = kC = kH = 1."""
    import math
    (L1, a1, b1), (L2, a2, b2) = lab1, lab2
    cm7 = ((math.hypot(a1, b1) + math.hypot(a2, b2)) / 2) ** 7
    g = 0.5 * (1 - math.sqrt(cm7 / (cm7 + 25 ** 7)))
    a1, a2 = a1 * (1 + g), a2 * (1 + g)
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    h1 = math.degrees(math.atan2(b1, a1)) % 360 if c1 else 0.0
    h2 = math.degrees(math.atan2(b2, a2)) % 360 if c2 else 0.0
    dh = 0.0
    if c1 * c2:
        dh = h2 - h1
        if dh > 180: dh -= 360
        elif dh < -180: dh += 360
    dH = 2 * math.sqrt(c1 * c2) * math.sin(math.radians(dh / 2))
    lm, cm = (L1 + L2) / 2, (c1 + c2) / 2
    if not c1 * c2: hm = h1 + h2
    elif abs(h1 - h2) <= 180: hm = (h1 + h2) / 2
    else: hm = (h1 + h2 + 360) / 2 if h1 + h2 < 360 else (h1 + h2 - 360) / 2
    t = (1 - 0.17 * math.cos(math.radians(hm - 30)) + 0.24 * math.cos(math.radians(2 * hm))
         + 0.32 * math.cos(math.radians(3 * hm + 6)) - 0.20 * math.cos(math.radians(4 * hm - 63)))
    rt = -2 * math.sqrt(cm ** 7 / (cm ** 7 + 25 ** 7)) * math.sin(math.radians(60 * math.exp(-((hm - 275) / 25) ** 2)))
    sl = 1 + 0.015 * (lm - 50) ** 2 / math.sqrt(20 + (lm - 50) ** 2)
    sc, sh = 1 + 0.045 * cm, 1 + 0.015 * cm * t
    dl, dc, dh_ = (L2 - L1) / sl, (c2 - c1) / sc, dH / sh
    return math.sqrt(max(0.0, dl * dl + dc * dc + dh_ * dh_ + rt * dc * dh_))


def lab_array(rgb):
    """numpy version of srgb_to_lab: Nx3 uint8 sRGB to Nx3 CIELAB (float64), same constants."""
    np = accel.modules()[0]
    lin = np.asarray(_LINEAR)[rgb]
    xyz = lin @ np.array([[0.4124564 / 0.95047, 0.2126729, 0.0193339 / 1.08883],
                          [0.3575761 / 0.95047, 0.7151522, 0.1191920 / 1.08883],
                          [0.1804375 / 0.95047, 0.0721750, 0.9503041 / 1.08883]])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)


def ciede2000_array(lab1, lab2):
    """numpy version of ciede2000 over Nx3 arrays (same formula, same branch rules)."""
    np = accel.modules()[0]
    L1, a1, b1 = lab1.T
    L2, a2, b2 = lab2.T
    cm7 = ((np.hypot(a1, b1) + np.hypot(a2, b2)) / 2) ** 7
    g = 0.5 * (1 - np.sqrt(cm7 / (cm7 + 25 ** 7)))
    a1, a2 = a1 * (1 + g), a2 * (1 + g)
    c1, c2 = np.hypot(a1, b1), np.hypot(a2, b2)
    h1 = np.where(c1 != 0, np.degrees(np.arctan2(b1, a1)) % 360, 0.0)
    h2 = np.where(c2 != 0, np.degrees(np.arctan2(b2, a2)) % 360, 0.0)
    both = c1 * c2 != 0
    dh = h2 - h1
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(both, dh, 0.0)
    dH = 2 * np.sqrt(c1 * c2) * np.sin(np.radians(dh / 2))
    lm, cm = (L1 + L2) / 2, (c1 + c2) / 2
    hm = np.where(np.abs(h1 - h2) <= 180, (h1 + h2) / 2, np.where(h1 + h2 < 360, (h1 + h2 + 360) / 2, (h1 + h2 - 360) / 2))
    hm = np.where(both, hm, h1 + h2)
    t = (1 - 0.17 * np.cos(np.radians(hm - 30)) + 0.24 * np.cos(np.radians(2 * hm))
         + 0.32 * np.cos(np.radians(3 * hm + 6)) - 0.20 * np.cos(np.radians(4 * hm - 63)))
    rt = -2 * np.sqrt(cm ** 7 / (cm ** 7 + 25 ** 7)) * np.sin(np.radians(60 * np.exp(-((hm - 275) / 25) ** 2)))
    sl = 1 + 0.015 * (lm - 50) ** 2 / np.sqrt(20 + (lm - 50) ** 2)
    sc, sh = 1 + 0.045 * cm, 1 + 0.015 * cm * t
    dl, dc, dh_ = (L2 - L1) / sl, (c2 - c1) / sc, dH / sh
    return np.sqrt(np.maximum(0.0, dl * dl + dc * dc + dh_ * dh_ + rt * dc * dh_))


def ring_color_difference(patch_rgb, base_rgb, region):
    """(mean, p95, samples) CIEDE2000 between patch and base at the same pixels of region, or None."""
    import math
    idx = on_indices(region, DE_SAMPLES)
    if not len(idx): return None
    if fast():
        np = accel.modules()[0]
        des = np.sort(ciede2000_array(lab_array(accel.to_array(patch_rgb).reshape(-1, 3)[idx]),
                                      lab_array(accel.to_array(base_rgb).reshape(-1, 3)[idx])))
        return float(des.mean()), float(des[max(0, math.ceil(0.95 * len(des)) - 1)]), len(des)
    pa, ba = patch_rgb.tobytes(), base_rgb.tobytes()
    des = sorted(ciede2000(srgb_to_lab(pa[3 * i:3 * i + 3]), srgb_to_lab(ba[3 * i:3 * i + 3])) for i in idx)
    return sum(des) / len(des), des[max(0, math.ceil(0.95 * len(des)) - 1)], len(des)


def seam_steps(hard, out_rgb, base_rgb):
    """(output, base) mean |dL*| between each mask edge pixel and its 4-neighbors outside the mask, or None."""
    P = pil()
    W, H = hard.size
    if fast():
        np, cv2 = accel.modules()
        m = accel.to_array(hard)
        edge = accel.to_mask(m > cv2.erode(m, accel.square(1)))
        idx = on_indices(edge, DE_SAMPLES)
        x, y = idx % W, idx // W
        src, dst = [], []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):  # same neighbor order and rule as the Pillow loop
            nx, ny = x + dx, y + dy
            ok = (nx >= 0) & (nx < W) & (ny >= 0) & (ny < H)
            ok[ok] = m[ny[ok], nx[ok]] == 0
            src.append(idx[ok]); dst.append(ny[ok] * W + nx[ok])
        src, dst = np.concatenate(src), np.concatenate(dst)
        if not len(src): return None
        def mean_step_np(img):
            flat = accel.to_array(img).reshape(-1, 3)
            return float(np.abs(lab_array(flat[src])[:, 0] - lab_array(flat[dst])[:, 0]).mean())
        return mean_step_np(out_rgb), mean_step_np(base_rgb)
    m = hard.tobytes()
    pairs = []
    for i in on_indices(P.ImageChops.subtract(hard, hard.filter(P.ImageFilter.MinFilter(3))), DE_SAMPLES):
        x, y = i % W, i // W
        pairs += [(i, ny * W + nx) for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
                  if 0 <= nx < W and 0 <= ny < H and not m[ny * W + nx]]
    if not pairs: return None
    def mean_step(data):
        L = lambda i: srgb_to_lab(data[3 * i:3 * i + 3])[0]
        return sum(abs(L(i) - L(j)) for i, j in pairs) / len(pairs)
    return mean_step(out_rgb.tobytes()), mean_step(base_rgb.tobytes())


def seam_grad(hard, out_rgb, base_rgb):
    """OpenCV only: (output, base) mean Sobel gradient magnitude of the gray image on the 2 px band across the mask
    edge, or None. Report only: a seam the blend added shows as a higher output value than the base's."""
    np, cv2 = accel.modules()
    m = accel.to_array(hard)
    band = cv2.dilate(m, accel.square(1)) > cv2.erode(m, accel.square(1))
    if not band.any(): return None
    def grad(img):
        gray = cv2.cvtColor(accel.to_array(img), cv2.COLOR_RGB2GRAY).astype(np.float32)
        return float(cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))[band].mean())
    return grad(out_rgb), grad(base_rgb)


def use_engine(args):
    """Select numpy/OpenCV or Pillow for an accelerated command (--engine, else IMAGE_STUDIO_ENGINE) and say which."""
    if accel is None:
        if (getattr(args, "engine", None) or os.environ.get("IMAGE_STUDIO_ENGINE", "")).strip().lower() == "fast":
            raise UsageError(f"engine fast needs accel.py next to {Path(__file__).name}; reinstall the image-verify skill")
        print("Engine: pillow", flush=True)
        return
    try: accel.select(getattr(args, "engine", None))
    except ValueError as exc: raise UsageError(str(exc)) from None
    print(f"Engine: {accel.label()}", flush=True)


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


def cmd_prepare_review(args):
    P = pil()
    path = existing_file(args.image, "--image")
    image = open_image(path).convert("RGB")
    out = Path(args.out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())): raise UsageError(f"{out} exists and is not empty; choose a new folder")
    out.mkdir(parents=True, exist_ok=True)
    W, H = image.size
    # at least 3x2 tiles, and no tile side over about 1024 px: larger views are shrunk by the model and cost the most tokens
    cols, rows = min(5, max(3, -(-W // 1000))), min(5, max(2, -(-H // 1000)))  # at most 5x5; above 5000 px tiles grow
    ov = max(0, args.overlap)
    tw, th = -(-(W + (cols - 1) * ov) // cols), -(-(H + (rows - 1) * ov) // rows)
    names = []
    def save(img, name):
        img.save(out / name, "PNG", compress_level=1); names.append(name)
    tw, th = min(tw, W), min(th, H)  # a side shorter than a tile is one tile
    corners = []
    for r in range(rows):
        for c in range(cols):
            corner = (max(0, min(c * (tw - ov), W - tw)), max(0, min(r * (th - ov), H - th)))
            if corner not in corners: corners.append(corner)
    for x, y in corners:
        save(image.crop((x, y, x + tw, y + th)), f"tile-{x}_{y}.png")
    e = min(90, W, H)
    save(image.crop((0, 0, W, e)), "edge-top.png"); save(image.crop((0, H - e, W, H)), "edge-bottom.png")
    save(image.crop((0, 0, e, H)), "edge-left.png"); save(image.crop((W - e, 0, W, H)), "edge-right.png")
    gray = image.convert("L"); gray.thumbnail((1024, 1024)); save(gray, "gray.png")
    thumb = image.copy(); thumb.thumbnail((120, 120)); save(thumb, "thumb.png")
    if args.approved:
        approved = open_image(existing_file(args.approved, "--approved")).convert("RGB")
        scale = lambda im: im.resize((max(1, round(im.size[0] * 600 / im.size[1])), 600), P.BILINEAR)
        a, b = scale(approved), scale(image)
        sheet = P.Image.new("RGB", (a.size[0] + b.size[0], 600)); sheet.paste(a, (0, 0)); sheet.paste(b, (a.size[0], 0))
        save(sheet, "lineup.png")
    print(f"Image {W}x{H}; {len(names)} views in {out} (tiles are 100% crops named by their top-left corner, {ov} px overlap):")
    print(" ".join(names))
    return 0


def trace_blade(image, start, end):
    """Follow the blade across perpendicular profiles from start (blade base) to end (tip).

    A pixel belongs to the blade when its color is closer to the blade color (sampled on the
    observed start-end segment) than to the background on either side of that profile.
    Returns [(x, y, width)] of blade centers; empty when no blade is found."""
    import math
    W, H = image.size
    px = image.load()
    (sx, sy), (ex, ey) = start, end
    length = math.hypot(ex - sx, ey - sy)
    ux, uy = (ex - sx) / length, (ey - sy) / length
    nx, ny = -uy, ux
    inside = lambda x, y: 0 <= x < W and 0 <= y < H
    # the blade color is sampled just past the observed blade base, the one spot known to be on the blade
    samples = [px[int(sx + ux * length * t), int(sy + uy * length * t)] for t in (0.0, 0.01, 0.02, 0.03, 0.04)]
    ref = tuple(sorted(c[i] for c in samples)[2] for i in range(3))
    dist = lambda a, b: (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
    band = max(20, round(length * 0.08))
    gap = max(3, band // 10)
    found, shift = [], 0.0  # shift follows the blade sideways when it drifts off the straight segment
    steps = max(10, min(200, round(length / 8)))
    for i in range(steps + 1):
        t = 0.03 + 0.92 * i / steps
        cx, cy = sx + ux * length * t + nx * shift, sy + uy * length * t + ny * shift
        if not (inside(cx + nx * band, cy + ny * band) and inside(cx - nx * band, cy - ny * band)): continue
        bg = (px[int(cx - nx * band), int(cy - ny * band)], px[int(cx + nx * band), int(cy + ny * band)])
        blade = [dist(c, ref) < min(dist(c, bg[0]), dist(c, bg[1]))
                 for c in (px[int(cx + nx * k), int(cy + ny * k)] for k in range(-band, band + 1))]
        hits = [k for k, b in enumerate(blade) if b]
        if not hits: continue
        seed = min(hits, key=lambda k: abs(k - band))
        lo = hi = seed
        while True:  # grow the run, bridging dark outlines and ridge lines up to `gap` px
            nxt = [k for k in hits if hi < k <= hi + gap + 1]
            if not nxt: break
            hi = max(nxt)
        while True:
            prv = [k for k in hits if lo - gap - 1 <= k < lo]
            if not prv: break
            lo = min(prv)
        if lo == 0 or hi == 2 * band: continue  # the run reached the profile edge: not a blade
        mid = (lo + hi) / 2 - band
        shift += mid
        found.append((cx + nx * mid, cy + ny * mid, hi - lo + 1))
    if len(found) < max(5, steps // 3): return []
    widths = sorted(f[2] for f in found)
    med = widths[len(widths) // 2]
    return [f for f in found if 0.4 * med <= f[2] <= 2.0 * med]


def cmd_axis_check(args):
    import math
    P = pil()
    if not 0 <= args.max_bend <= 90: raise UsageError("--max-bend must be a number of degrees from 0 to 90")
    if args.max_offset is not None and not args.max_offset > 0: raise UsageError("--max-offset must be a positive number of pixels")
    use_engine(args)
    path = existing_file(args.image, "--image")
    if args.guide:
        guide = Path(args.guide).expanduser()
        if guide.resolve() == path.resolve(): raise UsageError("--guide must not be the --image file")
        if guide.is_dir() or not guide.parent.is_dir(): raise UsageError(f"--guide {args.guide}: not a file path in an existing folder")
    image = open_image(path).convert("RGB")
    W, H = image.size
    points = []
    for raw in args.points:
        try: x, y = (float(v) for v in raw.split(","))
        except ValueError: raise UsageError(f"--points takes x,y pairs, got {raw!r}") from None
        if not (0 <= x < W and 0 <= y < H): raise UsageError(f"point {raw} is outside the image {W}x{H}")
        points.append((x, y))
    if len(points) < 2: raise UsageError("give at least the pommel and the tip, in order (e.g. pommel, crossguard, blade base, tip)")
    if any(math.hypot(b[0] - a[0], b[1] - a[1]) < 2 for a, b in zip(points, points[1:])): raise UsageError("two consecutive points are the same")
    (ax, ay), (bx, by) = points[0], points[-1]
    length = math.hypot(bx - ax, by - ay)
    if length < 20: raise UsageError("the first and last points must be at least 20 px apart")
    ux, uy = (bx - ax) / length, (by - ay) / length
    off = lambda x, y: (x - ax) * -uy + (y - ay) * ux  # signed distance from the red line, px
    start = points[-2] if len(points) >= 3 else (ax + (bx - ax) * 0.35, ay + (by - ay) * 0.35)
    spine = trace_blade(image, start, points[-1])
    width = sorted(s[2] for s in spine)[len(spine) // 2] if spine else 0
    if not spine and len(points) < 3:
        raise UsageError("blade not traced between the two points and no other point to check: add the crossguard or blade base")
    # 0.4 of the blade width, capped at 3% of the sword length so a wide blade does not hide a bend
    limit = args.max_offset or (max(4.0, min(0.4 * width, 0.03 * length)) if spine else max(4.0, 0.015 * length))
    print(f"Red line: first point {round(ax)},{round(ay)} -> last point {round(bx)},{round(by)} "
          f"({round(length)} px at {math.degrees(math.atan2(by - ay, bx - ax)):.1f} deg); limit {limit:.0f} px off the line")
    offsets = [off(x, y) for x, y in points[1:-1]]
    if offsets: print("Points off the red line: " + ", ".join(f"P{i + 2} {d:+.0f} px" for i, d in enumerate(offsets)))
    problems = [f"P{i + 2} is {abs(d):.0f} px off the red line" for i, d in enumerate(offsets) if abs(d) > limit]
    if spine:
        devs = [off(x, y) for x, y, _ in spine]
        worst = max(devs, key=abs)
        # angle of the traced spine against the red line (least squares slope of offset over distance along the line)
        ts = [(x - ax) * ux + (y - ay) * uy for x, y, _ in spine]
        mt, md = sum(ts) / len(ts), sum(devs) / len(devs)
        var = sum((t - mt) ** 2 for t in ts)
        tilt = abs(math.degrees(math.atan(sum((t - mt) * (d - md) for t, d in zip(ts, devs)) / var))) if var else 0.0
        print(f"Blade spine: {len(spine)} samples, blade about {width} px wide, at most {abs(worst):.0f} px off the red line, "
              f"{tilt:.1f} deg against it (limit {args.max_bend} deg)")
        if abs(worst) > limit: problems.append(f"the blade spine leaves the red line by {abs(worst):.0f} px")
        if tilt > args.max_bend: problems.append(f"the blade spine is {tilt:.1f} deg off the red line")
    else:
        print("Blade spine: not traced (no blade found between the last two points); only the points were checked")
    if problems:
        print("bent: " + "; ".join(problems))
        print("On the red line, the points belong at: " + "  ".join(
            f"{round(ax + ((x - ax) * ux + (y - ay) * uy) * ux)},{round(ay + ((x - ax) * ux + (y - ay) * uy) * uy)}" for x, y in points))
    else:
        print("straight: every point" + (" and the blade spine stay" if spine else " stays") + " on the red line")
    if args.guide:
        draw = P.ImageDraw.Draw(image)
        lw = max(2, min(W, H) // 400)
        if spine:  # outline both blade edges in cyan and mark the spine in yellow
            left = [(x - uy * w / 2, y + ux * w / 2) for x, y, w in spine]
            right = [(x + uy * w / 2, y - ux * w / 2) for x, y, w in spine]
            draw.line(left, fill=(0, 255, 255), width=lw); draw.line(right, fill=(0, 255, 255), width=lw)
            for x, y, _ in spine[::3]: draw.ellipse((x - lw, y - lw, x + lw, y + lw), fill=(255, 255, 0))
        draw.line((ax, ay, bx, by), fill=(255, 0, 0), width=lw)
        r = max(5, min(W, H) // 120)
        for i, (x, y) in enumerate(points):
            draw.ellipse((x - r, y - r, x + r, y + r), outline=(255, 255, 0), width=lw)
            draw.text((x + r + 2, y - r), f"P{i + 1}", fill=(255, 255, 0))
        image.save(args.guide, "PNG")
        print(f"Guide: {args.guide} (red: straight line from the first to the last point; cyan: traced blade edges; "
              "yellow dots: blade spine; yellow circles: your points)")
    return 1 if problems else 0


def cmd_blend(args):
    P = pil()
    use_engine(args)
    base_path, patch_path, mask_path = (existing_file(v, k) for v, k in ((args.base, "--base"), (args.patch, "--patch"), (args.mask, "--mask")))
    out = Path(args.out).expanduser()
    if out.resolve() in (base_path.resolve(), patch_path.resolve(), mask_path.resolve()): raise UsageError("--out must be a new file, not an input")
    if out.is_dir() or not out.parent.is_dir(): raise UsageError(f"--out {args.out}: not a file path in an existing folder")
    if out.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"): raise UsageError("--out must end in .png, .jpg, .jpeg, or .webp")
    if args.feather is not None and not 0 <= args.feather <= 64: raise UsageError("--feather must be 0 to 64 pixels")
    base, patch, mask_img = (open_8bit(p, k) for p, k in ((base_path, "--base"), (patch_path, "--patch"), (mask_path, "--mask")))
    alpha_out = base.mode in ("RGBA", "LA", "PA") or "transparency" in base.info
    base, patch = base.convert("RGBA"), patch.convert("RGBA")
    W, H = base.size
    hard = hard_mask(mask_img, base.size, "--mask", "--base")
    x0, y0 = parse_at(args.at) if args.at else (0, 0)
    if x0 < 0 or y0 < 0 or x0 + patch.size[0] > W or y0 + patch.size[1] > H:
        raise UsageError(f"the patch ({patch.size[0]}x{patch.size[1]} at {x0},{y0}) does not fit inside --base {W}x{H}; "
                         "resize it or pass --at")
    if args.no_align_check:
        print("warning: registration not checked (--no-align-check): the patch position was not verified against the base")
    elif not args.align:
        raise UsageError("blend needs --align D/align.json: run align-check with these inputs, open D/checker.png and "
                         "D/overlay.png, then align-check ... --accept (or pass --no-align-check when position cannot be wrong)")
    else:
        record = read_json(existing_file(args.align, "--align"), "--align record")
        if record.get("accepted") is not True:
            raise UsageError(f"{args.align} is not accepted: open checker.png and overlay.png next to it, then run align-check ... --accept")
        wrong = [k for k, path in (("base_sha256", base_path), ("patch_sha256", patch_path)) if record.get(k) != sha256_file(path)]
        if record.get("mask_sha256") is not None and record["mask_sha256"] != sha256_file(mask_path): wrong.append("mask_sha256")
        if record.get("at") != [x0, y0]: wrong.append(f"at (record {record.get('at')}, blend {x0},{y0})")
        if wrong:
            raise UsageError(f"{args.align} does not match the blend inputs ({', '.join(wrong)}): run align-check and --accept on these files")
        print(f"Registration: accepted in {args.align}")
    box = hard.getbbox()
    short = min(box[2] - box[0], box[3] - box[1])
    feather = args.feather
    if feather is None:
        feather = min(8, max(2, round(0.03 * short)))
        print(f"Feather: {feather} px (auto: 3% of the mask box short side {short} px, kept within 2-8)")
    elif feather > 0.05 * short:  # the automatic feather never warns about itself
        print(f"warning: feather {feather} px is over 5% of the mask box short side ({short} px); the soft band may show as a halo")
    placed = base.copy(); placed.paste(patch, (x0, y0))
    covered = P.Image.new("L", (W, H), 0); covered.paste(255, (x0, y0, x0 + patch.size[0], y0 + patch.size[1]))
    # work on the mask box plus a margin: the ring is the band just outside the mask that the patch also covers
    r = max(8, 2 * feather)
    m = r + feather * 2 + 2
    work = (max(0, box[0] - m), max(0, box[1] - m), min(W, box[2] + m), min(H, box[3] + m))
    hm, cw = hard.crop(work), covered.crop(work)
    if fast(): spread = P.Image.fromarray(accel.modules()[1].dilate(accel.to_array(hm), accel.square(r // 2)))
    else: spread = hm.filter(P.ImageFilter.MaxFilter(2 * (r // 2) + 1))
    ring = P.ImageChops.darker(P.ImageChops.subtract(spread, hm), cw)
    # fully transparent patch pixels carry no color the result will show: keep them out of the color statistics
    ring = P.ImageChops.darker(ring, placed.crop(work).getchannel("A").point(lambda v: 255 if v else 0))
    pw, bw = placed.crop(work), base.crop(work)
    rgb_p, rgb_b = pw.convert("RGB"), bw.convert("RGB")
    def delta(img):
        a, b = P.ImageStat.Stat(img, ring).mean, P.ImageStat.Stat(rgb_b, ring).mean
        return max(abs(x - y) for x, y in zip(a, b))
    if args.no_match: pass
    elif ring.getbbox():
        before = delta(rgb_p)
        sp, sb = P.ImageStat.Stat(rgb_p, ring), P.ImageStat.Stat(rgb_b, ring)
        luts = []
        for mp, dp, mb, db in zip(sp.mean, sp.stddev, sb.mean, sb.stddev):
            gain = min(1.25, max(0.8, db / dp)) if dp > 1 else 1.0
            luts += [max(0, min(255, round((v - mp) * gain + mb))) for v in range(256)]
        rgb_p = rgb_p.point(luts)
        print(f"Color match: ring difference {before:.1f} -> {delta(rgb_p):.1f} (largest channel mean, 0-255)")
    else:
        print("Color match: skipped (the patch does not cover any pixels around the mask)")
    # how well the (matched) patch agrees with the base where the feather mixes them: opaque ring pixels only
    opaque = P.ImageChops.darker(pw.getchannel("A"), bw.getchannel("A")).point(lambda v: 255 if v == 255 else 0)
    stats = ring_color_difference(rgb_p, rgb_b, P.ImageChops.darker(ring, opaque))
    mismatch = False
    if stats:
        mean, p95, n = stats
        mismatch = mean > DE_MEAN_LIMIT or p95 > DE_P95_LIMIT
        print(f"Ring dE2000 (patch vs base, {n} pixels): mean {mean:.2f}, p95 {p95:.2f} "
              f"(limits {DE_MEAN_LIMIT} and {DE_P95_LIMIT}" + (", not enforced with --no-match)" if args.no_match else ")"))
    else: print("Ring dE2000: skipped (no opaque pixels around the mask that the patch covers)")
    pw = P.Image.merge("RGBA", rgb_p.split() + (pw.getchannel("A"),))
    # the mask itself stays fully replaced; the feather only softens the band just outside it
    alpha = P.ImageChops.lighter(hm, hm.filter(P.ImageFilter.GaussianBlur(feather / 2))) if feather else hm
    alpha = P.ImageChops.darker(P.ImageChops.darker(alpha, cw), pw.getchannel("A"))  # a transparent patch pixel keeps the base
    result = base.copy(); result.paste(P.Image.composite(pw, bw, alpha), work[:2])
    if not alpha_out or out.suffix.lower() in (".jpg", ".jpeg"): result = result.convert("RGB")
    result.save(out)
    steps = seam_steps(hm, result.crop(work).convert("RGB"), rgb_b)
    if steps: print(f"seam_step: {steps[0]:.2f} mean |dL*| across the mask edge (base {steps[1]:.2f} at the same pixels)")
    else: print("seam_step: skipped (the mask has no edge inside the image)")
    grads = seam_grad(hm, result.crop(work).convert("RGB"), rgb_b) if fast() else None
    if grads: print(f"seam_grad: {grads[0]:.2f} mean Sobel gradient along the mask edge (base {grads[1]:.2f} at the same pixels; report only)")
    span = changed_mask(base, result).getbbox()
    print(f"Wrote {out}" + (f"; changed area {','.join(map(str, span))} (use as edit-check --bbox, or edit-check --mask "
                            f"{shlex.quote(str(mask_path))} --edge {feather})" if span else "; nothing changed"))
    if mismatch and not args.no_match:
        print(f"color mismatch: the patch differs from the base around the mask (dE2000 mean over {DE_MEAN_LIMIT} or p95 over "
              f"{DE_P95_LIMIT}); the output was written, but check the edge at 100% or regenerate the patch")
        return 1
    return 0


def cmd_edit_check(args):
    use_engine(args)
    before_path, after_path = existing_file(args.before, "--before"), existing_file(args.after, "--after")
    before, after = open_8bit(before_path, "--before"), open_8bit(after_path, "--after")
    if before.size != after.size:
        raise UsageError(f"size differs: {before.size[0]}x{before.size[1]} vs {after.size[0]}x{after.size[1]}")
    if not args.bbox and not args.mask: raise UsageError("give --bbox x0,y0,x1,y1, --mask M, or both")
    if args.edge and not args.mask: raise UsageError("--edge needs --mask")
    if not 0 <= args.edge <= 64: raise UsageError("--edge must be 0 to 64 pixels")
    w, h = before.size
    box = parse_bbox(args.bbox) if args.bbox else None
    if box and (box[2] > w or box[3] > h): raise UsageError(f"--bbox {box} is outside the image size {w}x{h}")
    if args.ring < 0: raise UsageError("--ring must be 0 or more")
    P = pil()
    hard = hard_mask(open_8bit(existing_file(args.mask, "--mask"), "--mask"), before.size, "--mask", "the images") if args.mask else None
    changed = changed_mask(before, after)
    failed = False
    if box:
        inside = P.Image.new("L", before.size, 0)
        inside.paste(255, tuple(box))
        outside = P.ImageChops.darker(changed, P.ImageChops.invert(inside))
        count_out, span = count_on(outside), outside.getbbox()
        print(f"Changed pixels inside the box: {count_on(P.ImageChops.darker(changed, inside))}")
        print(f"Changed pixels outside the box: {count_out}" + (f" (span {','.join(map(str, span))})" if span else ""))
        failed = count_out > 0
    if hard is not None:
        failed = mask_report(hard, changed, changed_mask(before, after, REAL_CHANGE_LEVEL), args.edge) or failed
        if not box: box = list(hard.getbbox())
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
    return 1 if failed else 0


def mask_report(hard, noise, real, edge):
    """Print edit-check --mask results; True when the edit fails (changes outside, or a mask that did nothing)."""
    P = pil()
    pct = lambda n, d: 100.0 * n / d if d else 0.0
    n_in = count_on(hard)
    band = grow(hard, edge)
    outside = P.ImageChops.invert(band)
    n_out = count_on(outside)
    in_real = count_on(P.ImageChops.darker(real, hard))
    out_noise, out_real_mask = count_on(P.ImageChops.darker(noise, outside)), P.ImageChops.darker(real, outside)
    out_real, span = count_on(out_real_mask), out_real_mask.getbbox()
    print(f"Mask: {n_in} px, box {','.join(map(str, hard.getbbox()))}")
    print(f"Changed inside the mask (over {REAL_CHANGE_LEVEL}/255): {pct(in_real, n_in):.2f}% ({in_real} px)")
    if edge:
        edge_only = P.ImageChops.subtract(band, hard)
        print(f"Edge band ({edge} px outside the mask, not checked): {pct(count_on(P.ImageChops.darker(real, edge_only)), count_on(edge_only)):.2f}% changed")
    print(f"Changed outside the mask: {pct(out_noise, n_out):.2f}% over {CHANGE_LEVEL}/255 (noise level, {out_noise} px), "
          f"{pct(out_real, n_out):.2f}% over {REAL_CHANGE_LEVEL}/255 ({out_real} px, limit {MASK_OUTSIDE_LIMIT * 100:.1f}%)"
          + (f" (span {','.join(map(str, span))})" if span else ""))
    problems = []
    if out_real > MASK_OUTSIDE_LIMIT * n_out:
        problems.append(f"changes outside the mask: {pct(out_real, n_out):.2f}% of outside pixels changed by more than "
                        f"{REAL_CHANGE_LEVEL}/255 (limit {MASK_OUTSIDE_LIMIT * 100:.1f}%)")
    need = min(n_in, max(4, MASK_EFFECT_MIN * n_in))  # at least 4 pixels, so one noise pixel never passes a small mask
    if in_real < need:
        problems.append(f"mask had no effect or is inverted: only {pct(in_real, n_in):.2f}% of mask pixels changed "
                        f"({in_real} px; need max(4, {MASK_EFFECT_MIN * 100:.1f}% of the mask))")
    for p in problems: print(f"FAIL: {p}")
    return bool(problems)


def auto_place(base, patch, hard):
    """align-check --auto (OpenCV): (x, y, scale, score, rival) of the patch in the base, None when it never fits, or
    a reason string when the patch (or its context outside the mask) is flat; rival is the best other place or None.
    A flat template scores 1.0 everywhere under TM_CCOEFF_NORMED, so it is refused instead of matched; equal scores
    prefer the scale closest to 1.

    TM_CCOEFF_NORMED over the scales in AUTO_SCALES on copies shrunk to about 1024 px, then refined at full size
    around the 8 best distinct places within a few pixels and +-0.02 scale (step 0.01). With a mask, the refinement matches only the patch's context:
    pixels outside the mask (grown by the search margin), so a repainted inside does not lower the score."""
    np, cv2 = accel.modules()
    B, T = accel.to_array(base), accel.to_array(patch)
    H, W = B.shape[:2]
    ph, pw = T.shape[:2]
    if T.reshape(-1, T.shape[2]).std(axis=0).max() < AUTO_FLAT_STD: return "the patch is flat"
    k = max(1, min(min(pw, ph) // 48, -(-max(W, H) // 1024)))  # shrink factor; the shrunk patch keeps 48 px or more
    shrink = lambda a, w, h: cv2.resize(a, (max(1, w), max(1, h)), interpolation=cv2.INTER_AREA if w < a.shape[1] else cv2.INTER_LINEAR)
    def peaks(img, templ, mask=None, count=1):
        """Up to count (score, x, y) best non-overlapping matches of templ in img."""
        if templ.shape[0] > img.shape[0] or templ.shape[1] > img.shape[1]: return []
        res = cv2.matchTemplate(img, templ, cv2.TM_CCOEFF_NORMED, mask=mask)
        res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)  # flat windows give NaN or inf
        out = []
        for _ in range(count):
            _, score, _, (x, y) = cv2.minMaxLoc(res)
            if score <= -1: break
            out.append((score, x, y))
            ry, rx = max(1, templ.shape[0] // 2), max(1, templ.shape[1] // 2)
            res[max(0, y - ry):y + ry + 1, max(0, x - rx):x + rx + 1] = -1.0  # next peak elsewhere
        return out
    rank = lambda c: (round(c[0], 4), -abs(c[1] - 1))  # (score, scale, ...): higher score first; on a tie the scale closest to 1
    small = shrink(B, round(W / k), round(H / k))
    coarse = []  # (score, scale, x, y) in full-size pixels: the best few places at every scale
    for s in AUTO_SCALES:
        coarse += [(v, s, x * k, y * k) for v, x, y in peaks(small, shrink(T, round(pw * s / k), round(ph * s / k)), count=5)]
    picked = []
    for cand in sorted(coarse, key=rank, reverse=True):  # refine the 8 best distinct places: repeated motifs can win when shrunk
        if all(abs(cand[2] - p[2]) > 2 * k or abs(cand[3] - p[3]) > 2 * k for p in picked): picked.append(cand)
        if len(picked) == 8: break
    margin = 2 * k + 4
    grown = accel.to_array(grow(hard, margin + 2)) if hard is not None else None  # once, not per place and scale
    places = []
    for _, s0, cx, cy in picked:
        best = None
        for s in sorted({round(min(1.12, max(0.88, s0 + d)), 2) for d in (-0.02, -0.01, 0.0, 0.01, 0.02)}):
            tw, th = round(pw * s), round(ph * s)
            templ = T if (tw, th) == (pw, ph) else shrink(T, tw, th)
            x0, y0 = max(0, cx - margin), max(0, cy - margin)
            window = B[y0:min(H, cy + th + margin), x0:min(W, cx + tw + margin)]
            mask = None
            if hard is not None:  # the patch's context: what lies outside the (grown) mask where the patch would sit
                ctx = np.zeros((th, tw), np.uint8)
                inside = grown[cy:cy + th, cx:cx + tw]
                ctx[:inside.shape[0], :inside.shape[1]] = np.where(inside > 0, 0, 255)
                if np.count_nonzero(ctx) >= 0.1 * tw * th: mask = ctx
            if mask is not None and templ[mask > 0].std(axis=0).max() < AUTO_FLAT_STD:
                cand = (1.0, s, cx, cy, True)  # a flat context fits anywhere (its score is 1.0 or undefined): refuse it
            else:
                found = peaks(window, templ, mask)
                cand = (found[0][0], s, x0 + found[0][1], y0 + found[0][2], False) if found else None
            if cand and (best is None or rank(cand) > rank(best)): best = cand
        if best: places.append(best)
    if not places: return None
    places.sort(key=rank, reverse=True)
    score, s, x, y, flat = places[0]
    if flat: return "the patch's context outside the mask is flat"
    rival = next((p for p in places[1:] if abs(p[2] - x) > 2 or abs(p[3] - y) > 2), None)
    return x, y, s, score, rival


def cmd_align_check(args):
    P = pil()
    base_path, patch_path = existing_file(args.base, "--base"), existing_file(args.patch, "--patch")
    if args.auto:
        if args.at: raise UsageError("--auto finds the position itself; give --auto or --at, not both")
        if accel is None: raise UsageError(f"align-check --auto needs accel.py next to {Path(__file__).name}; reinstall the image-verify skill")
        if not accel.available(): raise UsageError(f"align-check --auto needs numpy and OpenCV: {accel.INSTALL_HINT}")
    out_dir = Path(args.out_dir).expanduser()
    if out_dir.exists() and not out_dir.is_dir(): raise UsageError(f"--out-dir {args.out_dir} is a file, not a folder")
    if not out_dir.resolve().parent.is_dir(): raise UsageError(f"--out-dir {args.out_dir}: its parent folder does not exist")
    base, patch = open_8bit(base_path, "--base").convert("RGB"), open_8bit(patch_path, "--patch").convert("RGB")
    W, H = base.size
    pw, ph = patch.size
    hard = hard_mask(open_8bit(existing_file(args.mask, "--mask"), "--mask"), base.size, "--mask", "--base") if args.mask else None
    if args.auto:
        if pw > W or ph > H: raise UsageError(f"the patch ({pw}x{ph}) is larger than --base {W}x{H}")
        if min(pw, ph) < 8: raise UsageError(f"the patch ({pw}x{ph}) is too small to match; give --at")
        found = auto_place(base, patch, hard)
        if isinstance(found, str):
            print(f"no reliable match: {found} (under {AUTO_FLAT_STD:g} levels of variation, it matches anywhere); "
                  "give --at X,Y; nothing was written")
            return 1
        if found is None:
            print(f"no reliable match: the patch does not fit inside the base at any scale {AUTO_SCALES[0]:.2f}-{AUTO_SCALES[-1]:.2f}; give --at X,Y")
            return 1
        x, y, scale, score, rival = found
        print(f"Auto: best match at {x},{y}, scale {scale:.2f}, score {score:.3f} (TM_CCOEFF_NORMED"
              + (", context outside the mask" if hard is not None else "") + f"; scales {AUTO_SCALES[0]:.2f}-{AUTO_SCALES[-1]:.2f})")
        if score < AUTO_MIN_SCORE:
            print(f"no reliable match (score {score:.3f} < {AUTO_MIN_SCORE}): give --at X,Y; nothing was written")
            return 1
        if rival and rival[0] >= score - AUTO_TIE:
            print(f"no reliable match: {rival[2]},{rival[3]} matches as well (score {rival[0]:.3f}; a repeated motif); "
                  "give --at X,Y; nothing was written")
            return 1
        if abs(scale - 1) > AUTO_SCALE_LIMIT + 1e-9:
            print(f"the patch must be resized: it matches at scale {scale:.2f}, i.e. {round(pw * scale)}x{round(ph * scale)} instead of "
                  f"{pw}x{ph}. Resize it keeping aspect, then run align-check --auto on the resized patch; nothing was written")
            return 1
        args.at = f"{x},{y}"
    if args.at:
        x0, y0 = parse_at(args.at)
        if x0 < 0 or y0 < 0 or x0 + pw > W or y0 + ph > H:
            raise UsageError(f"the patch ({pw}x{ph} at {x0},{y0}) does not fit inside --base {W}x{H}")
        area, source = (x0, y0, x0 + pw, y0 + ph), f"--at {x0},{y0} and the patch size"
        mb = hard.getbbox() if hard is not None else None
        if mb and (mb[0] < area[0] or mb[1] < area[1] or mb[2] > area[2] or mb[3] > area[3]):
            raise UsageError(f"the mask box {','.join(map(str, mb))} reaches outside the patch area {','.join(map(str, area))}; "
                             "the patch would not cover the whole mask")
    else:
        area, source = (hard.getbbox(), "the mask box") if hard is not None else ((0, 0, W, H), "the whole base")
    aw, ah = area[2] - area[0], area[3] - area[1]
    diff = abs((pw / ph) / (aw / ah) - 1)
    if diff > ALIGN_ASPECT_LIMIT:
        raise UsageError(f"patch aspect {pw}x{ph} ({pw / ph:.3f}) differs from {source} {aw}x{ah} ({aw / ah:.3f}) by "
                         f"{diff * 100:.1f}% (limit {ALIGN_ASPECT_LIMIT * 100:.0f}%): crop or pad the patch to that aspect, "
                         "then resize keeping aspect; never stretch it")
    print(f"Area: {','.join(map(str, area))} ({aw}x{ah}, from {source})")
    if (pw, ph) != (aw, ah):
        patch = patch.resize((aw, ah), P.BILINEAR)
        print(f"Patch scaled {pw}x{ph} -> {aw}x{ah} for the preview (aspect within {ALIGN_ASPECT_LIMIT * 100:.0f}%); "
              f"resize it the same way, then blend --at {area[0]},{area[1]}")
    checker, overlay, record_path = out_dir / "checker.png", out_dir / "overlay.png", out_dir / "align.json"
    inputs = {p.resolve() for p in (base_path, patch_path) + ((Path(args.mask).expanduser(),) if args.mask else ())}
    if {checker.resolve(), overlay.resolve(), record_path.resolve()} & inputs:
        raise UsageError(f"--out-dir {args.out_dir} would overwrite an input (checker.png, overlay.png or align.json); choose another folder")
    record = {"base_sha256": sha256_file(base_path), "patch_sha256": sha256_file(patch_path),
              "mask_sha256": sha256_file(Path(args.mask).expanduser()) if args.mask else None,
              "at": [area[0], area[1]], "accepted": False}
    if args.accept:
        if (pw, ph) != (aw, ah):
            raise UsageError(f"the patch was scaled for the preview; resize it to {aw}x{ah} keeping aspect, run align-check "
                             "on the resized patch, look at the views, then accept")
        if not (checker.is_file() and overlay.is_file()):
            raise UsageError(f"no checker.png and overlay.png in {out_dir}: run align-check without --accept first and look at them")
        old = read_json(record_path, "align.json (run align-check without --accept first)")
        changed = [k for k in ("base_sha256", "patch_sha256", "mask_sha256", "at") if old.get(k) != record[k]]
        if changed:
            raise UsageError(f"{', '.join(changed)} differ from {record_path}: the views show other inputs; run align-check "
                             "again without --accept and look at the new views")
        record["accepted"] = True
        atomic_write(record_path, dump_json(record))
        print(f"Accepted: {record_path} (blend --align {shlex.quote(str(record_path))} --at {area[0]},{area[1]} with these exact files)")
        return 0
    region = base.crop(area)
    s = max(24, min(aw, ah) // 12)
    cells = P.Image.new("L", (aw, ah), 0)
    draw = P.ImageDraw.Draw(cells)
    for gy in range(0, ah, s):
        for gx in range(0, aw, s):
            if (gx // s + gy // s) % 2: draw.rectangle((gx, gy, gx + s - 1, gy + s - 1), fill=255)
    out_dir.mkdir(exist_ok=True)
    P.Image.composite(patch, region, cells).save(checker, "PNG")
    P.Image.blend(region, patch, 0.5).save(overlay, "PNG")
    atomic_write(record_path, dump_json(record))
    print(f"Checker: {checker} (base and patch in alternating {s} px squares; lines that jump at square borders are misaligned)")
    print(f"Overlay: {overlay} (50/50 mix; doubled or ghosted edges are misaligned)")
    print(f"Record: {record_path} (accepted: false). Open both views; when nothing jumps or ghosts, run the same command with --accept")
    return 0


def boundary_offset(a, b, cap):
    """Largest distance (px, Euclidean) from a boundary pixel of either 0/255 mask to the nearest boundary pixel of the
    other; None when some boundary pixel has none within cap px. Only boundary pixels are visited: each one searches the
    rows around it with bytes.find, nearest rows first, so the cost follows the boundary length, not the image size."""
    import math
    P = pil()
    ba, bb = a.getbbox(), b.getbbox()
    box = (min(ba[0], bb[0]), min(ba[1], bb[1]), max(ba[2], bb[2]), max(ba[3], bb[3]))
    pad = cap + 2  # zero border: shapes touching the image edge get a boundary there, and row searches never wrap
    W, H = box[2] - box[0] + 2 * pad, box[3] - box[1] + 2 * pad
    def edge(mask):
        canvas = P.Image.new("L", (W, H), 0); canvas.paste(mask.crop(box), (pad, pad))
        return P.ImageChops.subtract(canvas, canvas.filter(P.ImageFilter.MinFilter(3)))
    ea, eb = edge(a), edge(b)
    if fast():  # exact Euclidean distance transform: the same distances, computed for every pixel at once
        np, cv2 = accel.modules()
        A, B = accel.to_array(ea) > 0, accel.to_array(eb) > 0
        far = 0.0
        for src, dst in ((A, B), (B, A)):
            dist = cv2.distanceTransform(np.where(dst, 0, 255).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
            far = max(far, float(dist[src].max()))
        return None if far > cap else far
    worst, none = 0, (cap + 1) ** 2
    for src, dst in ((ea, eb), (eb, ea)):
        data, todo = dst.tobytes(), P.ImageChops.subtract(src, dst).tobytes()  # pixels on both boundaries are 0 px off
        i = todo.find(255)
        while i >= 0:
            y, x = divmod(i, W)
            best, dy = none, 0
            while dy * dy < best:
                r = math.isqrt(best - dy * dy)
                for row in {(y + dy) * W, (y - dy) * W}:
                    j = data.find(255, row + x, row + x + r + 1)
                    if j >= 0: best = min(best, (j - row - x) ** 2 + dy * dy)
                    k = data.rfind(255, row + x - r, row + x + 1)
                    if k >= 0: best = min(best, (row + x - k) ** 2 + dy * dy)
                dy += 1
            if best > cap * cap: return None
            worst = max(worst, best)
            i = todo.find(255, i + 1)
    return math.sqrt(worst)


def cmd_shape_check(args):
    import math
    P = pil()
    if not 0 <= args.max_iou_loss < 1: raise UsageError("--max-iou-loss must be from 0 to below 1 (0.01 = IoU at least 0.99)")
    if not 0 <= args.max_aspect < 1: raise UsageError("--max-aspect must be from 0 to below 1 (0.01 = 1%)")
    if args.max_edge is not None and not 0 < args.max_edge <= 256: raise UsageError("--max-edge must be 0 to 256 pixels (above 0)")
    use_engine(args)
    before = open_8bit(existing_file(args.before_mask, "--before-mask"), "--before-mask")
    after = open_8bit(existing_file(args.after_mask, "--after-mask"), "--after-mask")
    a = hard_mask(before, before.size, "--before-mask", "itself")
    b = hard_mask(after, before.size, "--after-mask", "--before-mask")
    W, H = a.size
    iou = count_on(P.ImageChops.darker(a, b)) / count_on(P.ImageChops.lighter(a, b))
    (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = a.getbbox(), b.getbbox()
    ra, rb = (ax1 - ax0) / (ay1 - ay0), (bx1 - bx0) / (by1 - by0)
    aspect = abs(rb / ra - 1)
    limit = args.max_edge if args.max_edge is not None else max(2.0, SHAPE_EDGE_SHARE * max(W, H))
    cap = min(SHAPE_EDGE_CAP, int(math.ceil(max(16, 3 * limit))))  # the search cost grows with the cap squared
    offset = boundary_offset(a, b, cap)
    print(f"Before: {count_on(a)} px, box {ax0},{ay0},{ax1},{ay1}; after: {count_on(b)} px, box {bx0},{by0},{bx1},{by1}")
    print(f"IoU: {iou:.4f} (limit {1 - args.max_iou_loss:.4f} or more)")
    print(f"Box aspect: {ra:.4f} -> {rb:.4f}, change {aspect * 100:.2f}% (limit {args.max_aspect * 100:.2f}%)")
    print(f"Max boundary offset: " + (f"{offset:.2f} px" if offset is not None else f"over {cap} px") + f" (limit {limit:.2f} px)")
    problems = []
    if iou < 1 - args.max_iou_loss: problems.append(f"IoU {iou:.4f} is under {1 - args.max_iou_loss:.4f}: the silhouette changed")
    if aspect > args.max_aspect: problems.append(f"box aspect changed {aspect * 100:.2f}%: the object was stretched or squashed")
    if offset is None or offset > limit:
        problems.append("boundary moved " + (f"{offset:.2f}" if offset is not None else f"over {cap}") + f" px: the outline drifted")
    for p in problems: print(f"FAIL: {p}")
    if not problems: print("pass: the silhouette kept its shape, proportions and outline")
    return 1 if problems else 0


def cmd_crop_check(args):
    path = existing_file(args.image, "--image")
    image = open_8bit(path, "--image")
    image = image.convert("RGBA" if has_alpha(image) else "RGB")
    W, H = image.size
    fx0, fy0, fx1, fy1 = parse_bbox([args.focus], "--focus")
    if fx1 > W or fy1 > H: raise UsageError(f"--focus {args.focus} is outside the image size {W}x{H}")
    display = None
    if args.display:
        try: display = tuple(int(v) for v in args.display.lower().split("x"))
        except ValueError: display = ()
        if len(display) != 2 or min(display) <= 0: raise UsageError(f"--display takes WxH in pixels, e.g. 1280x720, got {args.display!r}")
    out_dir = Path(args.out_dir).expanduser() if args.out_dir else None
    if out_dir is not None:
        if out_dir.exists() and not out_dir.is_dir(): raise UsageError(f"--out-dir {args.out_dir} is a file, not a folder")
        if not out_dir.resolve().parent.is_dir(): raise UsageError(f"--out-dir {args.out_dir}: its parent folder does not exist")
        if path.resolve().parent == out_dir.resolve() and path.name in {f"crop-{w}x{h}.png" for w, h in CROP_RATIOS}:
            raise UsageError(f"--out-dir {args.out_dir} would overwrite --image; choose another folder")
    fw, fh = fx1 - fx0, fy1 - fy0
    print(f"Image {W}x{H}; focus {fx0},{fy0},{fx1},{fy1} ({fw}x{fh})")
    problems, crops = [], []
    for rw, rh in CROP_RATIOS:
        cw, ch = (H * rw // rh, H) if W * rh >= H * rw else (W, W * rh // rw)  # the largest crop of this ratio
        x0 = min(max(0, round((fx0 + fx1 - cw) / 2)), W - cw)  # centered on the focus, then kept inside the image
        y0 = min(max(0, round((fy0 + fy1 - ch) / 2)), H - ch)
        crop = (x0, y0, x0 + cw, y0 + ch)
        name = f"{rw}:{rh}"
        if min(cw, ch) < 2 or abs(cw * rh - ch * rw) > max(rw, rh):  # rounding down left a crop of another shape
            print(f"{name}: image too small for this ratio (largest crop {cw}x{ch})")
            problems.append(f"{name}: image too small for this ratio"); continue
        if crop[0] <= fx0 and crop[1] <= fy0 and crop[2] >= fx1 and crop[3] >= fy1:
            print(f"{name}: ok, crop {','.join(map(str, crop))} ({cw}x{ch}), focus {100.0 * fw * fh / (cw * ch):.1f}% of the crop")
        else:
            print(f"{name}: focus does not fit (focus {fw}x{fh}, largest {name} crop {cw}x{ch})")
            problems.append(f"{name}: focus does not fit")
        crops.append((f"crop-{rw}x{rh}.png", crop))
    if display:
        dw, dh = display
        factor = min(W / dw, H / dh)
        print(f"Display {dw}x{dh}: the image is {factor:.2f}x the display (needs {CROP_DISPLAY_FACTOR}x on both axes for sharp high-DPI screens)")
        if W < CROP_DISPLAY_FACTOR * dw or H < CROP_DISPLAY_FACTOR * dh:
            problems.append(f"image {W}x{H} is under {CROP_DISPLAY_FACTOR}x the {dw}x{dh} display ({factor:.2f}x)")
    if out_dir is not None:
        out_dir.mkdir(exist_ok=True)
        for name, crop in crops: image.crop(crop).save(out_dir / name, "PNG")
        print(f"Crops: {out_dir} ({', '.join(n for n, _ in crops)})")
    for p in problems: print(f"FAIL: {p}")
    return 1 if problems else 0


def drop_small_components(mask, min_area):
    """Pillow engine: (mask, components, dropped) with 8-connected components under min_area pixels removed.

    Works on runs of on pixels row by row inside the mask box (union-find of runs that touch, diagonals included),
    so the cost follows the number of runs, not the image size; the same result as cv2.connectedComponentsWithStats."""
    P = pil()
    box = mask.getbbox()
    if not box: return mask, 0, 0
    bw = box[2] - box[0]
    data = mask.crop(box).tobytes()
    runs, parent = [], []  # runs: (row, start, end) with end exclusive
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    prev = []
    for y in range(box[3] - box[1]):
        row = data[y * bw:(y + 1) * bw]
        cur, j = [], 0
        for m in re.finditer(rb"[^\x00]+", row):
            i, start, end = len(runs), m.start(), m.end()
            runs.append((y, start, end)); parent.append(i); cur.append(i)
            while j < len(prev) and runs[prev[j]][2] < start: j += 1  # runs above that end left of this one
            k = j
            while k < len(prev) and runs[prev[k]][1] <= end:  # overlap or touch diagonally
                ri, rk = find(i), find(prev[k])
                if ri != rk: parent[ri] = rk
                k += 1
        prev = cur
    area = {}
    for i, (_, a, b) in enumerate(runs): area[find(i)] = area.get(find(i), 0) + b - a
    out = bytearray(len(data))
    for i, (y, a, b) in enumerate(runs):
        if area[find(i)] >= min_area: out[y * bw + a:y * bw + b] = b"\xff" * (b - a)
    result = P.Image.new("L", mask.size, 0)
    result.paste(P.Image.frombytes("L", (bw, box[3] - box[1]), bytes(out)), box[:2])
    return result, len(area), sum(1 for v in area.values() if v < min_area)


def cmd_mask_from_diff(args):
    P = pil()
    if not 0 <= args.threshold <= 254: raise UsageError("--threshold must be 0 to 254 (a channel must differ by more than it)")
    if not 0 <= args.grow <= 64: raise UsageError("--grow must be 0 to 64 pixels")
    if args.min_area < 0: raise UsageError("--min-area must be 0 or more pixels")
    use_engine(args)
    before_path, after_path = existing_file(args.before, "--before"), existing_file(args.after, "--after")
    out = Path(args.out).expanduser()
    if out.resolve() in (before_path.resolve(), after_path.resolve()): raise UsageError("--out must be a new file, not --before or --after")
    if out.is_dir() or not out.parent.is_dir(): raise UsageError(f"--out {args.out}: not a file path in an existing folder")
    if out.suffix.lower() != ".png": raise UsageError("--out must end in .png (an 8-bit gray mask, 0 or 255)")
    before, after = open_8bit(before_path, "--before"), open_8bit(after_path, "--after")
    if before.size != after.size:
        raise UsageError(f"size differs: {before.size[0]}x{before.size[1]} vs {after.size[0]}x{after.size[1]}")
    changed = changed_mask(before, after, args.threshold)
    n = count_on(changed)
    print(f"Changed pixels (a channel differs by more than {args.threshold}/255): {n}")
    if not n:
        print("no change: no pixel differs by more than --threshold; nothing was written")
        return 1
    if args.min_area > 1 and fast():
        np, cv2 = accel.modules()
        count, labels, stats, _ = cv2.connectedComponentsWithStats(accel.to_array(changed), connectivity=8)
        keep = stats[:, cv2.CC_STAT_AREA] >= args.min_area
        keep[0] = False  # label 0 is the unchanged background
        changed = accel.to_mask(keep[labels])
        print(f"Components (8-connected): {count - 1}; dropped {int((~keep[1:]).sum())} under {args.min_area} px")
    elif args.min_area > 1:
        changed, count, dropped = drop_small_components(changed, args.min_area)
        print(f"Components (8-connected): {count}; dropped {dropped} under {args.min_area} px")
    mask = grow(changed, args.grow)
    box = mask.getbbox()
    if not box:
        print(f"no change left: every changed area was under --min-area {args.min_area} px; nothing was written")
        return 1
    mask.save(out, "PNG")
    print(f"Wrote {out}: {count_on(mask)} px after growing {args.grow} px, box {','.join(map(str, box))} "
          "(blend --mask, edit-check --mask)")
    return 0


EPILOG = """\
subcommands:
  init --project PATH --brand ID         example: python3 studio_state.py init --project . --brand acme
  approve deliverable --name N --file F [--width W --height H --format PNG|JPEG|WEBP|ZIP] [--alpha required|forbidden|any] [--quote T]
                                         example: python3 studio_state.py approve deliverable --name poster --file poster.png --width 1200 --height 800 --format PNG
  defect add --deliverable N --bbox x0,y0,x1,y1 --kind logo|seam|artifact|scope|color|other --note T [--source user|agent] [--quote T] [--wide]
                                         records image_size; a user box on the region of an earlier user complaint (any status; same
                                         image size, or w/h within 2% compared as fractions; IoU >= 0.1, its center inside the old box,
                                         or 60% of the old box inside it) is a repeat: it records repeat_of and needs a lesson and a
                                         construction rule (agent defects and scope requests with --quote never are, nor match)
                                         example: python3 studio_state.py defect add --deliverable poster --bbox 100,50,200,150 --kind seam --note "visible seam"
  defect close --id D1 --status resolved|wontfix --note T [--quote T]
                                         example: python3 studio_state.py defect close --id D1 --status resolved --note "feathered seam"
  brief [--max-lines 40]                 example: python3 studio_state.py brief
  gate --deliverable N [--file F] [--run RUN]
                                         example: python3 studio_state.py gate --deliverable poster
  verdict --run RUN (--id D1 --status pass|fail|uncertain --evidence T | --from verdicts.json) [--reviewer self|independent] [--crop 100|200]
                                         example: python3 studio_state.py verdict --run 20261018T000000Z-abc --id D1 --status pass --evidence "seam gone at 100%"
  pref add [--brand B] --rule T --check T [--evidence T] [--confirmed]
                                         example: python3 studio_state.py pref add --brand acme --rule "No bevels" --check "inspect edges" --confirmed
  lesson add --mistake T --cause T --check T [--worked T] [--defect D1] [--kind K] [--brand B]
                                         example: python3 studio_state.py lesson add --defect D4 --mistake "delivered a soft poster" --cause "upscaled a generated patch" --check "compare at 100% before delivery"
  lesson list [--brand B]                example: python3 studio_state.py lesson list --brand acme
  construction add --defect D1 --object T --rule T (--ref FILE [--ref FILE ...] | --quote T)
                                         how an object is physically built, from real reference photos or the user's words; stored in the
                                         store's construction.jsonl with each ref's path and sha256; the gate fails a repeat defect without one
                                         example: python3 studio_state.py construction add --defect D7 --object "booster pack" --rule "torn top strip stays attached at one end; its length equals the tear edge" --ref refs/tear-1.jpg --ref refs/tear-2.jpg
  construction list                      example: python3 studio_state.py construction list
  taste add --note T [--aspect color|line|composition|detail|lighting|text|style|other] [--quote T] [--deliverable N] [--brand B]
                                         example: python3 studio_state.py taste add --aspect color --note "deep blue night palette with warm gold accents" --quote "love this palette"
  taste list [--brand B]                 example: python3 studio_state.py taste list --brand acme
  brand set --brand B [--color NAME=#RRGGBB[:role]] [--font ROLE=Family] [--logo FILE] [--ref FILE=role] [--do T] [--dont T] [--remove KEY]
                                         example: python3 studio_state.py brand set --brand acme --color gold=#E1C178:accent --font title=Cinzel --logo logo.png --ref style.png=style --dont "no 3D render look"
  brand show [--brand B]                 example: python3 studio_state.py brand show --brand acme
  map --deliverable N [--file F] --out F  draw every open defect on one image for the user to confirm at once
                                         example: python3 studio_state.py map --deliverable poster --out defect-map.png
  prepare-review --image F --out DIR [--approved A]
                                         every designer-review view in one call: overlapping tiles named tile-X_Y.png, edges, gray, thumb, lineup
                                         example: python3 studio_state.py prepare-review --image poster.png --approved v6.png --out views
  axis-check --image F --points X,Y X,Y ... [--max-offset PX] [--max-bend 2] [--guide out.png] [--engine E]
                                         points from pommel (first) to tip (last); the red pommel-to-tip line is the axis, the blade spine is traced
                                         from the pixels between the last two points; exit 1 when a point or the spine leaves the line
                                         example: python3 studio_state.py axis-check --image hero.png --points 25,355 230,540 250,573 850,1570 --guide guide.png
  align-check --base B --patch P --out-dir D [--at X,Y | --auto] [--mask M] [--accept]
                                         before blend: writes D/checker.png (base and patch in alternating squares) and D/overlay.png
                                         (50/50 mix) over the patch area (--at, else the mask box, else the whole base), and D/align.json
                                         {base_sha256, patch_sha256, mask_sha256|null, at, accepted: false}; exit 2 when the
                                         patch must be scaled into an area whose aspect differs by more than 1% (never stretch a patch).
                                         Open both views; then the same command with --accept re-hashes the inputs and sets accepted: true
                                         (exit 2 when the inputs changed, the views are missing, or the patch was scaled for the preview).
                                         Without --mask the record has mask_sha256 null and blend accepts any mask. The record stops
                                         accidental skips; it is not a security boundary (a hand-edited align.json is trusted).
                                         --auto (needs numpy and OpenCV, exit 2 with an install hint without them) finds --at itself:
                                         cv2.matchTemplate TM_CCOEFF_NORMED over patch scales 0.90-1.10 (step 0.02, refined to 0.01), with
                                         --mask only the patch's context outside the mask; prints "Auto: best match at X,Y, scale S, score V",
                                         then continues as with --at X,Y (views and align.json). Exit 1, nothing written: score under 0.8,
                                         another place within 0.01 of it, or a flat patch or masked context (std under 2 levels)
                                         ("no reliable match ... give --at"); equal scores prefer scale 1; a scale more than 1% from 1
                                         ("the patch must be resized" to the printed WxH; it is never resized for you)
                                         example: python3 studio_state.py align-check --base v6.png --patch patch.png --at 1200,400 --out-dir align
                                         example: python3 studio_state.py align-check --base v6.png --patch patch.png --mask mask.png --auto --out-dir align
  blend --base B --patch P --mask M --out F (--align D/align.json | --no-align-check) [--at X,Y] [--feather PX] [--no-match] [--engine E]
                                         exit 2 unless --align names an accepted align.json whose hashes and at match these inputs;
                                         --no-align-check skips it and prints "warning: registration not checked".
                                         paste a repair patch through a mask: matches its color to the ring around the mask, feathers the edge
                                         (default 3% of the mask box short side, 2-8 px; a passed --feather warns over 5%), prints ring dE2000 mean/p95,
                                         seam_step (mean |dL*| across the mask edge) and the changed area for edit-check; always writes the
                                         output, exit 1 "color mismatch" when dE2000 mean > 2.0 or p95 > 3.5 (report only with --no-match).
                                         With numpy/OpenCV it also prints seam_grad (mean Sobel gradient on the 2 px band across the mask
                                         edge, output vs base; report only, never changes the exit code)
                                         example: python3 studio_state.py blend --base v6.png --patch patch.png --mask mask.png --at 1200,400 --align align/align.json --out v7.png
  edit-check --before A --after B [--bbox x0,y0,x1,y1] [--mask M [--edge PX]] [--ring 24] [--out F] [--engine E]
                                         at least one of --bbox and --mask (both run both checks); 16-bit inputs are refused. --bbox: changed pixels outside the box (exit 1 if any). --mask (same rule as blend: 128+ is in,
                                         transparent is out): % of mask pixels changed over 12/255; outside it, % over 8/255 (noise) and
                                         over 12/255 (exit 1 above 0.1%); exit 1 when under max(4 px, 0.5% of the mask) changed (no effect or inverted);
                                         --edge skips the blend feather band. Writes one before|after|changes view
                                         example: python3 studio_state.py edit-check --before v7.png --after v8.png --mask mask.png --edge 2
  shape-check --before-mask A --after-mask B [--max-iou-loss 0.01] [--max-aspect 0.01] [--max-edge PX] [--engine E]
                                         silhouette masks of one protected object before and after an edit (same size, blend's mask rule):
                                         exit 1 when IoU < 1 - max-iou-loss, the box w/h ratio changes by more than max-aspect, or a
                                         boundary pixel is farther than max-edge (default max(2, 0.1% of the long side)) from the other outline;
                                         the search stops at 3x the limit (16-512 px) and reports "over N px" beyond it
                                         example: python3 studio_state.py shape-check --before-mask bottle-v6.png --after-mask bottle-v7.png
  mask-from-diff --before B --after A --out M.png [--threshold 24] [--grow 5] [--min-area 16] [--engine E]
                                         repair mask from two images: pixels where a channel differs by more than --threshold, components under
                                         --min-area px dropped (8-connected; OpenCV or a pure-Python run labeling, the same mask on both
                                         engines), then grown --grow px (square). Writes an 8-bit gray PNG of 0/255; refuses to
                                         overwrite --before or --after; exit 1 and no file when nothing changed (or nothing is left)
                                         example: python3 studio_state.py mask-from-diff --before v6.png --after edited.png --out mask.png
  crop-check --image F --focus x0,y0,x1,y1 [--display WxH] [--out-dir D]
                                         largest 16:9, 4:5, 1:1 and 9:16 crops centered on the focus and kept inside the image: ok with the
                                         focus share of the crop, "focus does not fit", or "image too small for this ratio"; --display: the image must be 2x WxH on both axes;
                                         --out-dir writes crop-16x9.png, crop-4x5.png, crop-1x1.png, crop-9x16.png; exit 1 on any problem
                                         example: python3 studio_state.py crop-check --image hero.png --focus 820,300,1240,900 --display 1440x810 --out-dir crops
  hook session-start | hook stop         example: python3 studio_state.py hook session-start < payload.json

approve, defect, construction, brief, gate and verdict find the store by walking up from --project or the current folder.
init creates it; pref add does not use the project store; lessons (lessons.jsonl) and taste notes (brands/<brand>/taste.jsonl, taste.jsonl) live in ${IMAGE_STUDIO_HOME:-~/.image-studio}, shared by every task; hooks use the cwd from the hook input.
gate fails a wrong size and says whether the aspect matches (w/h within 0.025); a PNG/JPEG/WebP over 1 MB gets a warning, not a fail.
engine (axis-check, blend, edit-check, shape-check, mask-from-diff): --engine auto|pillow|fast, else IMAGE_STUDIO_ENGINE, else auto.
auto uses numpy + OpenCV when both import, pillow never does, fast exits 2 with an install hint without them; the first output
line says "Engine: numpy/opencv" or "Engine: pillow". Both engines give the same verdict; optional install (Python 3.9+):
uv run --with pillow --with jsonschema --with numpy==2.0.2 --with opencv-python-headless==4.11.0.86 python3 studio_state.py ...
exit codes: 0 ok / gate pass, 1 gate fail, edit-check found changes outside the box or mask (or a mask with no effect), axis-check found a bend,
blend found a color mismatch (output still written), shape-check found a changed silhouette, crop-check found a crop or size problem,
align-check --auto found no reliable match or a scale to fix, or mask-from-diff found no change,
2 bad input or no store (blend without an accepted align record also exits 2)
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
    p.add_argument("--wide", action="store_true")
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
    p.add_argument("--run", required=True); p.add_argument("--id")
    p.add_argument("--status", choices=("pass", "fail", "uncertain"))
    p.add_argument("--evidence"); p.add_argument("--reviewer", choices=("self", "independent"), default="self")
    p.add_argument("--from", dest="from_file", help='JSON list of {"id", "status", "evidence"[, "crop"]}: every verdict of the run in one call')
    p.add_argument("--crop", choices=("100", "200"), default="100")
    p.set_defaults(func=cmd_verdict)

    p = sub.add_parser("map", parents=[common])
    p.add_argument("--deliverable", required=True); p.add_argument("--file"); p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_map)

    p = sub.add_parser("prepare-review")
    p.add_argument("--image", required=True); p.add_argument("--out", required=True)
    p.add_argument("--approved"); p.add_argument("--overlap", type=int, default=40)
    p.set_defaults(func=cmd_prepare_review)

    p = sub.add_parser("axis-check")
    p.add_argument("--engine", choices=ENGINES, help="auto (default; or IMAGE_STUDIO_ENGINE), pillow, or fast (needs numpy and OpenCV)")
    p.add_argument("--image", required=True); p.add_argument("--points", required=True, nargs="+")
    p.add_argument("--max-bend", type=float, default=2.0); p.add_argument("--max-offset", type=float); p.add_argument("--guide")
    p.set_defaults(func=cmd_axis_check)

    p = sub.add_parser("blend")
    p.add_argument("--engine", choices=ENGINES, help="auto (default; or IMAGE_STUDIO_ENGINE), pillow, or fast (needs numpy and OpenCV)")
    p.add_argument("--base", required=True); p.add_argument("--patch", required=True); p.add_argument("--mask", required=True)
    p.add_argument("--out", required=True); p.add_argument("--at"); p.add_argument("--feather", type=int)
    p.add_argument("--no-match", action="store_true")
    gate = p.add_mutually_exclusive_group()
    gate.add_argument("--align", help="D/align.json written by align-check and accepted with align-check ... --accept")
    gate.add_argument("--no-align-check", action="store_true", help="skip the registration check (prints a warning)")
    p.set_defaults(func=cmd_blend)

    p = sub.add_parser("edit-check")
    p.add_argument("--engine", choices=ENGINES, help="auto (default; or IMAGE_STUDIO_ENGINE), pillow, or fast (needs numpy and OpenCV)")
    p.add_argument("--before", required=True); p.add_argument("--after", required=True)
    p.add_argument("--bbox", nargs="+"); p.add_argument("--mask"); p.add_argument("--edge", type=int, default=0)
    p.add_argument("--ring", type=int, default=24); p.add_argument("--out", default="edit-check.png")
    p.set_defaults(func=cmd_edit_check)

    p = sub.add_parser("align-check")
    p.add_argument("--base", required=True); p.add_argument("--patch", required=True); p.add_argument("--at"); p.add_argument("--mask")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--accept", action="store_true", help="after opening checker.png and overlay.png: mark D/align.json accepted")
    p.add_argument("--auto", action="store_true", help="find --at with OpenCV template matching (needs numpy and OpenCV)")
    p.set_defaults(func=cmd_align_check)

    p = sub.add_parser("shape-check")
    p.add_argument("--engine", choices=ENGINES, help="auto (default; or IMAGE_STUDIO_ENGINE), pillow, or fast (needs numpy and OpenCV)")
    p.add_argument("--before-mask", required=True); p.add_argument("--after-mask", required=True)
    p.add_argument("--max-iou-loss", type=float, default=SHAPE_IOU_LOSS); p.add_argument("--max-aspect", type=float, default=SHAPE_ASPECT)
    p.add_argument("--max-edge", type=float)
    p.set_defaults(func=cmd_shape_check)

    p = sub.add_parser("mask-from-diff")
    p.add_argument("--engine", choices=ENGINES, help="auto (default; or IMAGE_STUDIO_ENGINE), pillow, or fast (needs numpy and OpenCV)")
    p.add_argument("--before", required=True); p.add_argument("--after", required=True); p.add_argument("--out", required=True)
    p.add_argument("--threshold", type=int, default=24); p.add_argument("--grow", type=int, default=5)
    p.add_argument("--min-area", type=int, default=16)
    p.set_defaults(func=cmd_mask_from_diff)

    p = sub.add_parser("crop-check")
    p.add_argument("--image", required=True); p.add_argument("--focus", required=True); p.add_argument("--display"); p.add_argument("--out-dir")
    p.set_defaults(func=cmd_crop_check)

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

    construction = sub.add_parser("construction").add_subparsers(dest="what", metavar="add|list", required=True)
    p = construction.add_parser("add", parents=[common])
    p.add_argument("--defect", required=True); p.add_argument("--object", required=True); p.add_argument("--rule", required=True)
    p.add_argument("--ref", action="append", help="a real reference photo of the same action (repeat for more)")
    p.add_argument("--quote", help="the user's own words explaining how the object is built")
    p.set_defaults(func=cmd_construction_add)
    p = construction.add_parser("list", parents=[common])
    p.set_defaults(func=cmd_construction_list)

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
    if fcntl is None or getattr(args, "command", None) not in ("approve", "defect", "gate", "verdict", "construction"): return None
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
    if accel is not None: accel.reset()  # only the accelerated commands select an engine, each run anew
    try: return args.func(args)
    except UsageError as exc: print(f"error: {exc}", file=sys.stderr)
    except OSError as exc: print(f"error: {exc}", file=sys.stderr)
    except Exception as exc: print(f"error: unexpected {exc.__class__.__name__}: {exc}", file=sys.stderr)
    finally:
        if lock is not None: lock.close()
    return 2


if __name__ == "__main__":
    sys.exit(main())
