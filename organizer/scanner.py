from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

from .config import Config
from .media import describe as describe_image
from .textract import extract, guess_kind

MAX_TEXT_BYTES = 200_000

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif",
    ".bmp", ".tiff", ".tif", ".avif",
}

# Windows reparse points (junctions, symlinks) and cloud placeholders.
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000


@dataclass
class FileInfo:
    id: str
    path: str
    root: str
    rel_dir: str
    name: str
    ext: str
    size: int
    mtime: float
    kind: str
    text: str
    text_chars: int
    note: str = ""
    is_dir: bool = False
    item_count: int = 0
    hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def file_id(path: Path) -> str:
    return hashlib.sha1(str(path).lower().encode("utf-8", "ignore")).hexdigest()[:12]


def scan(cfg: Config, on_progress=None) -> tuple[list[FileInfo], list[str]]:
    """Walk every root and return (files, errors). Read-only."""
    files: list[FileInfo] = []
    errors: list[str] = []
    now = time.time()
    min_age = cfg.min_file_age_hours * 3600
    vault = str(cfg.vault).lower()
    size_cap = cfg.max_size_mb * 1024 * 1024

    for root in cfg.roots:
        if not root.exists():
            errors.append(f"root not found: {root}")
            continue
        if is_protected(root, cfg):
            errors.append(f"root is protected, skipped: {root}")
            continue
        for path, is_dir in _walk(root, cfg):
            if is_dir:
                try:
                    files.append(_project_info(path, root, cfg, _bundle_kind(path, cfg)))
                except OSError as exc:
                    errors.append(f"{path}: {exc}")
                if on_progress:
                    on_progress(len(files), path)
                continue

            low = str(path).lower()
            if low.startswith(vault):
                continue
            try:
                st = path.stat()
            except OSError as exc:
                errors.append(f"{path}: {exc}")
                continue
            if min_age and (now - st.st_mtime) < min_age:
                continue

            attrs = getattr(st, "st_file_attributes", 0)
            if attrs & (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS):
                # cloud placeholder: reading it would force a download
                files.append(_info(path, root, st, "", "cloud placeholder - not downloaded"))
                if on_progress:
                    on_progress(len(files), path)
                continue

            if st.st_size > size_cap:
                files.append(_info(path, root, st, "", "too large - name only"))
            elif path.suffix.lower() in IMAGE_EXTS:
                # No text to extract, but there is still a lot to read: size,
                # EXIF camera, capture date, and what the filename says it is.
                text, hints = describe_image(path)
                # A photo of a paper document is otherwise invisible. Only try
                # OCR when the image is a candidate document/scan, not generic wallpapers or frame dumps:
                stem_low = path.stem.lower()
                path_str_low = str(path).lower()
                doc_image_cands = (
                    "scan", "doc", "bill", "receipt", "invoice", "aadhaar", "aadhar",
                    "pan", "passport", "tax", "salary", "slip", "cert", "form",
                    "statement", "resume", "marksheet", "degree", "prescription", "report",
                    "voter", "license", "marks", "grade", "10th", "12th",
                    "project", "subject", "topic", "nasa", "diagram", "architecture",
                    "notes", "whiteboard", "spec", "api", "chemistry", "physics", "biology",
                    "office", "presentation", "slide"
                )
                is_doc_candidate = (
                    bool({"scan", "document"} & set(hints))
                    or any(k in stem_low for k in doc_image_cands)
                    or any(k in path_str_low for k in ("document", "scan", "aadhaar", "pan", "resume", "salary", "medical", "project", "subject", "office", "nasa"))
                )
                is_wa_cand = (
                    "whatsapp" in path_str_low
                    or "wa0" in stem_low
                    or "img-wa" in stem_low
                    or "greeting" in stem_low
                    or "meme" in stem_low
                    or "gm_" in stem_low
                    or "suprabhat" in stem_low
                )

                if (is_doc_candidate and not ({"wallpaper", "art"} & set(hints))) or is_wa_cand:
                    from .ocr import ocr_any
                    from .photo_intel import RE_GREETING, RE_MEME
                    from .doc_intel import recognize_document

                    seen_text = ocr_any(path, max_chars=MAX_TEXT_BYTES)
                    if seen_text:
                        text = f"{seen_text}\n{text}"
                        doc_check = recognize_document(path.name, seen_text, str(path.parent))
                        if doc_check.doc_type:
                            hints = list(dict.fromkeys(hints + ["scan", "document"]))
                        elif RE_GREETING.search(seen_text):
                            hints = list(dict.fromkeys(hints + ["whatsapp_junk", "greeting"]))
                        elif RE_MEME.search(seen_text):
                            hints = list(dict.fromkeys(hints + ["whatsapp_junk", "meme"]))
                        elif len(seen_text) >= 24:
                            hints = list(dict.fromkeys(hints + ["scan", "document"]))
                info = _info(path, root, st, text, "" if text else "no readable text")
                info.hints = hints
                files.append(info)
            else:
                text = extract(path, max_bytes=MAX_TEXT_BYTES)
                files.append(_info(path, root, st, text, "" if text else "no readable text"))
            if on_progress:
                res = on_progress(len(files), path)
                if res is False:
                    break
    return files, errors


def _info(path: Path, root: Path, st: os.stat_result, text: str, note: str = "") -> FileInfo:
    try:
        rel = path.parent.relative_to(root)
        rel_dir = "" if str(rel) == "." else str(rel)
    except ValueError:
        rel_dir = ""
    return FileInfo(
        id=file_id(path),
        path=str(path),
        root=str(root),
        rel_dir=rel_dir,
        name=path.name,
        ext=path.suffix.lower(),
        size=st.st_size,
        mtime=st.st_mtime,
        kind=guess_kind(path),
        text=text[:2500],
        text_chars=len(text),
        note=note,
    )


def _is_reparse(entry: os.DirEntry) -> bool:
    """True for junctions, symlinks and other reparse points."""
    try:
        if entry.is_symlink():
            return True
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return True
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def _walk(root: Path, cfg: Config):
    """Explicit stack walk. Never follows junctions, never revisits a real path.

    Yields (path, is_dir). A directory is yielded instead of descended into when
    it looks like a project, so a code repo is handled as one unit.
    """
    seen: set[str] = set()
    stack: list[tuple[Path, int]] = [(root, 0)]

    while stack:
        current, depth = stack.pop()
        try:
            real = os.path.realpath(current)
        except OSError:
            continue
        if real in seen:
            continue
        seen.add(real)

        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:
            continue

        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if _is_reparse(entry):
                        continue
                    if entry.name.lower() in cfg.ignore_dirs or entry.name.startswith("."):
                        continue
                    child = Path(entry.path)
                    if is_protected(child, cfg):
                        continue
                    if cfg.treat_projects_as_units and _project_markers(child, cfg):
                        yield child, True
                        continue
                    # A folder of linked HTML pages is a book, not a pile of
                    # files. Collapse it to one unit so its links survive.
                    bundle = _bundle_kind(child, cfg)
                    if bundle:
                        yield child, True
                        continue
                    if depth + 1 <= cfg.max_depth:
                        stack.append((child, depth + 1))
                    continue

                if not entry.is_file(follow_symlinks=False):
                    continue
                name = entry.name
                low = name.lower()
                if low in cfg.ignore_names:
                    continue
                if name.startswith("~$") or name.startswith(".~lock"):
                    continue
                if Path(name).suffix.lower() in cfg.ignore_exts:
                    continue
                p = Path(entry.path)
                if is_protected(p, cfg):
                    continue
                yield p, False
            except OSError:
                continue


def is_protected(path: Path, cfg: Config) -> bool:
    """True if this path is inside a folder the user marked off-limits."""
    low = str(path).lower().rstrip("\\/")
    for guard in cfg.protected_paths:
        g = str(guard).lower().rstrip("\\/")
        if low == g or low.startswith(g + os.sep):
            return True
    return False


def _project_markers(path: Path, cfg: Config) -> list[str]:
    """Marker files that say 'this folder is a project'. Empty list if not one."""
    found: list[str] = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.name.lower() in cfg.project_markers:
                    found.append(entry.name)
    except OSError:
        return []
    return found


# A folder like this is an offline book / saved web docs: many pages plus the
# assets that make the links work. Moving the pages individually destroys it.
_BUNDLE_MARKERS = ("toc.ncx", "content.opf", "mimetype", "index.hmtl")
_WEB_PAGE_EXTS = {".html", ".htm", ".xhtml", ".shtml"}


def _bundle_kind(path: Path, cfg: Config) -> str:
    """Return a description if this folder is a self-contained document bundle.

    The test is proportion, not a magic filename: if a folder holds a lot of
    web pages and *also* the pictures/styles/scripts they reference, then it is
    one book or one saved site. Splitting it would break every relative link.
    """
    pages = assets = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                low = entry.name.lower()
                try:
                    if entry.is_dir(follow_symlinks=False):
                        continue
                    if low in _BUNDLE_MARKERS:
                        return "document bundle"
                    ext = os.path.splitext(low)[1]
                except OSError:
                    continue
                if ext in _WEB_PAGE_EXTS:
                    pages += 1
                elif ext in {".gif", ".png", ".jpg", ".jpeg", ".css", ".js", ".xml",
                             ".ncx", ".opf", ".woff", ".ttf", ".svg"}:
                    assets += 1
    except OSError:
        return ""

    if pages >= 15:
        return f"document bundle ({pages} linked pages)"
    if pages >= 5 and assets >= pages:
        return f"document bundle ({pages} pages + {assets} assets)"
    return ""


def _dir_size(path: Path, cap: int = 20000) -> tuple[int, int]:
    total = count = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d.lower() not in {"node_modules", ".git", ".venv", "__pycache__"}]
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
            count += 1
            if count >= cap:
                return total, count
    return total, count


def _project_info(path: Path, root: Path, cfg: Config, bundle: str = "") -> FileInfo:
    st = path.stat()
    markers = _project_markers(path, cfg)
    size, count = _dir_size(path)
    try:
        rel = path.parent.relative_to(root)
        rel_dir = "" if str(rel) == "." else str(rel)
    except ValueError:
        rel_dir = ""
    if bundle:
        # A book / saved docs folder. The words inside its pages are the best
        # signal of what it is about, so read one page's title into the text.
        text = f"{path.name} {bundle} ebook book reference documentation"
        kind = "Document bundle"
    else:
        text = f"{path.name} {' '.join(markers)} project folder repository"
        kind = "Project folder"
    return FileInfo(
        id=file_id(path),
        path=str(path),
        root=str(root),
        rel_dir=rel_dir,
        name=path.name,
        ext="",
        size=size,
        mtime=st.st_mtime,
        kind=kind,
        text=text,
        text_chars=len(text),
        note=bundle or f"folder with {count} files - moved as one unit",
        is_dir=True,
        item_count=count,
    )
