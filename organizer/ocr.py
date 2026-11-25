"""Read the text off paper: OCR for images and scanned PDFs.

The organiser's promise is "read the file and understand what it is for". For a
typed document that is easy. For a photo of a bill, a screenshot of a chat, or a
PDF that is really a scan, there was nothing to read - those files were invisible
and got guessed by filename.

Three tiers, best available first, and it never crashes if none are present:

  1. tesseract   - the real engine. Best quality, works offline.
  2. pymupdf     - can pull a PDF's embedded text, and render pages to images
                   for tesseract to read when the PDF has no text layer.
  3. nothing     - returns "" and the caller falls back to filename only.

Tesseract lives outside Python, so we look in the usual Windows install spots
instead of hoping it is on PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".gif"}

# Enough to catch a heading and a few lines of real content.
MAX_OCR_CHARS = 4000
# A page with fewer characters than this is treated as "no text layer".
_SCANNED_PDF_THRESHOLD = 24

_TESS_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)

_cache: dict[str, str | None] = {}


def tesseract_path() -> str | None:
    """Locate tesseract once, then remember it."""
    if "bin" in _cache:
        return _cache["bin"]
    found = shutil.which("tesseract")
    if not found:
        for cand in _TESS_CANDIDATES:
            if Path(cand).exists():
                found = cand
                break
    if not found:
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Tesseract-OCR/tesseract.exe"
        if local.exists():
            found = str(local)
    _cache["bin"] = found
    return found


def available() -> bool:
    return tesseract_path() is not None


def ocr_image(path: Path, max_chars: int = MAX_OCR_CHARS) -> str:
    """Read text out of an image file. Returns "" if OCR is unavailable."""
    exe = tesseract_path()
    if not exe:
        return ""
    try:
        # stdout, no temp output file. psm 3 = normal page layout.
        out = subprocess.run(
            [exe, str(path), "stdout", "--psm", "3"],
            capture_output=True,
            timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = out.stdout.decode("utf-8", "ignore")
    except (OSError, subprocess.SubprocessError):
        return ""
    return _tidy(text, max_chars)


def ocr_pdf(path: Path, max_pages: int = 1, max_chars: int = MAX_OCR_CHARS) -> str:
    """Text from a PDF, falling back to rendering pages and OCRing them."""
    try:
        import pymupdf  # type: ignore
    except ImportError:
        try:
            import fitz as pymupdf  # older name
        except ImportError:
            return ""

    try:
        doc = pymupdf.open(str(path))
    except Exception:
        return ""

    try:
        # Fast path: the PDF already has selectable text.
        embedded: list[str] = []
        for page in doc[:min(len(doc), 3)]:
            try:
                embedded.append(page.get_text() or "")
            except Exception:
                continue
        text = _tidy("\n".join(embedded), max_chars)
        if len(text) >= _SCANNED_PDF_THRESHOLD:
            return text

        # Slow path: it is a scan. Render first page and OCR the picture fast.
        if not available():
            return ""
        chunks: list[str] = []
        for page in doc[:min(len(doc), max_pages)]:
            try:
                pix = page.get_pixmap(dpi=130)
            except Exception:
                continue
            with tempfile.TemporaryDirectory() as tmp:
                img = Path(tmp) / "page.png"
                try:
                    pix.save(str(img))
                except Exception:
                    continue
                got = ocr_image(img, max_chars)
            if got:
                chunks.append(got)
            if sum(len(c) for c in chunks) >= max_chars:
                break
        return _tidy("\n".join(chunks), max_chars)
    finally:
        try:
            doc.close()
        except Exception:
            pass


def ocr_any(path: Path, max_chars: int = MAX_OCR_CHARS) -> str:
    """Route by extension. Safe to call on anything."""
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            return ocr_pdf(path, max_chars=max_chars)
        if ext in IMAGE_EXTS:
            return ocr_image(path, max_chars)
    except Exception:
        return ""
    return ""


def _tidy(text: str, max_chars: int) -> str:
    """Drop the blank-line noise tesseract produces, keep the words."""
    lines = [ln.strip() for ln in text.splitlines()]
    kept = [ln for ln in lines if ln]
    return "\n".join(kept)[:max_chars].strip()
