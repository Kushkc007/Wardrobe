"""OCR tests: the agent must actually read paper, not guess from filenames."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from organizer.ocr import available, ocr_any, tesseract_path  # noqa: E402


def _make_invoice_png(path: Path) -> bool:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    img = Image.new("RGB", (900, 240), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 50), "INVOICE INV-2024-0042", fill="black")
    d.text((40, 110), "Total Due Rs 18500 GSTIN 27AABCU9603R1ZM", fill="black")
    d.text((40, 170), "NEFT IFSC HDFC0001234", fill="black")
    img.save(path)
    return True


def test_tesseract_is_found():
    # Tesseract is an optional external program; skip where it is not installed.
    if not available():
        pytest.skip("tesseract not installed or not found")
    assert Path(tesseract_path()).exists()


def test_reads_text_out_of_a_real_image(tmp: Path = None):
    if not available():
        return
    tmp = tmp or Path(__file__).parent / "_ocr_tmp.png"
    try:
        if not _make_invoice_png(tmp):
            return
        text = ocr_any(tmp)
        low = text.lower()
        assert "invoice" in low, text
        assert "18500" in low.replace(",", "").replace(".", ""), text
        assert "ifsc" in low or "hdfc" in low, text
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def test_long_words_survive_the_cleanup():
    if not available():
        return
    tmp = Path(__file__).parent / "_ocr_tmp2.png"
    try:
        if not _make_invoice_png(tmp):
            return
        text = ocr_any(tmp)
        assert "\n\n\n" not in text, "blank line noise should be stripped"
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def test_unknown_file_is_safe():
    # Must never raise, whatever it is handed.
    assert ocr_any(Path(__file__).resolve()) == ""


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL {name}: {exc}")
    print("\nall good" if not failures else f"\n{failures} failed")
    sys.exit(1 if failures else 0)
