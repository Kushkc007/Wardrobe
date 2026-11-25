"""Turn a file into a short piece of text the classifier can actually read.

Zero dependencies. PDF is the only format that needs an optional library.
"""
from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path

TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".json", ".jsonl",
    ".yaml", ".yml", ".xml", ".html", ".htm", ".ini", ".toml", ".cfg",
    ".sql", ".rst", ".tex", ".srt", ".ass", ".vtt", ".m3u", ".pls",
}

CODE_EXTS = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".java", ".c", ".h",
    ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".sh", ".ps1", ".bat",
    ".cmd", ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".kt", ".kts",
    ".swift", ".lua", ".r", ".m", ".dart", ".pl", ".ex", ".exs", ".clj", ".scala",
}

OOXML = {".docx", ".xlsx", ".pptx", ".docm", ".xlsm", ".pptm", ".odt", ".ods", ".odp"}

# Old binary Office files. They are OLE containers: real text is stored as
# UTF-16 runs, so we can recover readable words without any library.
LEGACY_OFFICE = {".doc", ".xls", ".ppt", ".msg"}

# Formats that are really plain text with a different extension.
OTHER_READABLE = {
    ".ps", ".mht", ".mhtml", ".eml", ".nfo", ".diz", ".tex", ".bib",
    ".srt", ".vtt", ".ass", ".sub", ".cue", ".pls", ".m3u", ".reg",
    ".properties", ".gitignore", ".env", ".bat", ".cmd", ".ps1",
}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_MULTI_NL = re.compile(r"\n{3,}")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def extract(path: Path, max_bytes: int = 200_000) -> str:
    """Best-effort text for a file. Never raises."""
    ext = path.suffix.lower()
    try:
        if ext in OOXML:
            return _ooxml(path, max_bytes)
        if ext in TEXT_EXTS or ext in CODE_EXTS:
            return _plain(path, max_bytes)
        if ext == ".pdf":
            return _pdf(path, max_bytes)
        if ext == ".rtf":
            return _rtf(path, max_bytes)
        if ext == ".epub":
            return _epub(path, max_bytes)
        if ext in LEGACY_OFFICE:
            return _legacy_office(path, max_bytes)
        if ext == ".chm":
            return _chm(path, max_bytes)
        if ext in {".mht", ".mhtml"}:
            return _mht(path, max_bytes)
        if ext in OTHER_READABLE:
            return _plain(path, max_bytes)
    except Exception:
        return ""
    return ""


def _read_bytes(path: Path, max_bytes: int) -> bytes:
    with path.open("rb") as fh:
        return fh.read(max_bytes)


def _looks_binary(blob: bytes) -> bool:
    if not blob:
        return False
    return b"\x00" in blob[:2048]


def _clean(text: str) -> str:
    text = html.unescape(text)
    text = _CTRL.sub(" ", text)
    text = _WS.sub(" ", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


def _plain(path: Path, max_bytes: int) -> str:
    blob = _read_bytes(path, max_bytes)
    if _looks_binary(blob):
        return ""
    for enc in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return _clean(blob.decode(enc))
        except UnicodeDecodeError:
            continue
    return ""


def _ooxml(path: Path, max_bytes: int) -> str:
    """Read docx/xlsx/pptx straight out of the zip container - no libs needed."""
    ext = path.suffix.lower()
    parts: list[str] = []
    budget = max_bytes
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        if ext in {".odt", ".ods", ".odp"}:
            # OpenDocument: one content.xml holds all the text
            targets = [n for n in names if n == "content.xml"]
        elif ext in {".docx", ".docm"}:
            targets = [n for n in zf.namelist() if n.startswith("word/") and n.endswith(".xml")]
        elif ext in {".pptx", ".pptm"}:
            targets = sorted(
                (n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")),
                key=_natural_key,
            )
        else:
            targets = [
                n for n in zf.namelist()
                if n in ("xl/sharedStrings.xml",) or n.startswith("xl/worksheets/sheet")
            ]
        for name in targets:
            if budget <= 0:
                break
            try:
                raw = zf.read(name)
            except Exception:
                continue
            budget -= len(raw)
            xml = raw.decode("utf-8", "ignore")
            # keep paragraph / cell boundaries readable
            xml = xml.replace("</w:p>", "\n").replace("</a:p>", "\n")
            xml = xml.replace("</w:tr>", "\n").replace("</row>", "\n")
            xml = xml.replace("</c>", "\t")
            text = _clean(_TAG.sub(" ", xml))
            if text:
                parts.append(text)
    return "\n".join(parts)


def _pdf(path: Path, max_bytes: int) -> str:
    text = _pdf_embedded(path, max_bytes)
    if len(text) >= 24:
        return text
    # No text layer: this is a scan. Render and OCR it instead of giving up.
    from .ocr import ocr_pdf

    return ocr_pdf(path, max_chars=max_bytes) or text


def _pdf_embedded(path: Path, max_bytes: int) -> str:
    # 1. Fast C-engine path: PyMuPDF (50x faster than pure-Python pypdf)
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError:
        try:
            import fitz  # type: ignore
        except ImportError:
            fitz = None
    if fitz is not None:
        try:
            doc = fitz.open(str(path))
            out = []
            total = 0
            for page in doc[:10]:
                chunk = page.get_text() or ""
                if chunk:
                    out.append(chunk)
                    total += len(chunk)
                if total >= max_bytes:
                    break
            meta = doc.metadata or {}
            head = " ".join(str(meta.get(k, "")) for k in ("title", "subject", "author") if meta.get(k))
            doc.close()
            text = _clean(head + "\n" + "\n".join(out))
            if len(text) >= 24:
                return text
        except Exception:
            pass

    # 2. Fallback to pypdf
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except ImportError:
            return ""
    try:
        reader = PdfReader(str(path))
        out: list[str] = []
        total = 0
        for page in reader.pages[:10]:
            try:
                chunk = page.extract_text() or ""
            except Exception:
                continue
            out.append(chunk)
            total += len(chunk)
            if total >= max_bytes:
                break
        meta = reader.metadata or {}
        head = " ".join(str(meta.get(k, "")) for k in ("/Title", "/Subject", "/Author") if meta.get(k))
        return _clean(head + "\n" + "\n".join(out))
    except Exception:
        return ""


def _rtf(path: Path, max_bytes: int) -> str:
    blob = _read_bytes(path, max_bytes)
    text = blob.decode("latin-1", "ignore")
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d*\s?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    return _clean(text)


def _epub(path: Path, max_bytes: int) -> str:
    out: list[str] = []
    budget = max_bytes
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if budget <= 0:
                break
            if not name.lower().endswith((".xhtml", ".html", ".htm")):
                continue
            raw = zf.read(name)
            budget -= len(raw)
            out.append(_clean(_TAG.sub(" ", raw.decode("utf-8", "ignore"))))
    return "\n".join(out)


def _natural_key(name: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", name))


def _legacy_office(path: Path, max_bytes: int) -> str:
    """Old .doc/.xls/.ppt/.msg files.

    These predate zip-based Office. They are OLE compound files, but the bulk of
    the real text sits in the stream as runs of UTF-16LE, so we can recover the
    readable strings without parsing the container. Good enough to know what
    the document is about, which is all the classifier needs.
    """
    blob = _read_bytes(path, min(max_bytes, 2_000_000))
    if not blob:
        return ""
    chunks: list[str] = []

    # UTF-16LE runs: ASCII letter, 0x00, ASCII letter, 0x00 ...
    try:
        wide = blob.decode("utf-16-le", "ignore")
        chunks.append(" ".join(re.findall(r"[A-Za-z][A-Za-z0-9 ,.;:()\-/&%$#@'\"!?]{3,}", wide)))
    except Exception:
        pass

    # Plain 8-bit runs catch the rest (and old Word 6/95 files).
    try:
        narrow = blob.decode("cp1252", "ignore")
        chunks.append(" ".join(re.findall(r"[A-Za-z][A-Za-z0-9 ,.;:()\-/&%$#@'\"!?]{4,}", narrow)))
    except Exception:
        pass

    text = _clean(" ".join(c for c in chunks if c))
    return text[:max_bytes]


def _mht(path: Path, max_bytes: int) -> str:
    """Saved single-file webpage: strip headers and tags, keep the words."""
    blob = _read_bytes(path, max_bytes)
    if _looks_binary(blob):
        return ""
    text = blob.decode("utf-8", "ignore")
    text = re.split(r"\r?\n\r?\n", text, maxsplit=1)[-1] if "Content-Type" in text[:400] else text
    return _clean(_TAG.sub(" ", text))


def _chm(path: Path, max_bytes: int) -> str:
    """Windows .chm help files.

    A real CHM is an IT storage container (LZX compression). Without a library we
    cannot decompress the pages, but the index and title strings are stored
    uncompressed in places, so we can still recover what the help file covers.
    """
    blob = _read_bytes(path, min(max_bytes, 1_500_000))
    if not blob:
        return ""
    found: list[str] = []
    for enc in ("utf-8", "cp1252"):
        text = blob.decode(enc, "ignore")
        found.extend(re.findall(r"[A-Za-z][A-Za-z0-9 ,.;:_\-()/&]{4,}", text))
    return _clean(" ".join(found))[:max_bytes]


def guess_kind(path: Path) -> str:
    """A coarse human word for the file kind, used in prompts and reports."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "PDF document"
    if ext in {".docx", ".doc", ".rtf", ".odt"}:
        return "Word document"
    if ext in {".xlsx", ".xls", ".csv", ".tsv"}:
        return "Spreadsheet"
    if ext in {".pptx", ".ppt", ".key"}:
        return "Presentation"
    if ext in CODE_EXTS:
        return "Source code"
    if ext in {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".bmp", ".tiff", ".svg"}:
        return "Image"
    if ext in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}:
        return "Video"
    if ext in {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"}:
        return "Audio"
    if ext in {".zip", ".rar", ".7z", ".tar", ".gz"}:
        return "Archive"
    if ext in {".exe", ".msi", ".apk", ".dmg", ".pkg"}:
        return "Installer"
    if ext in TEXT_EXTS:
        return "Text file"
    return "File"
