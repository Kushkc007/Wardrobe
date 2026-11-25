"""Every common document format must be opened and read, not guessed by name.

This locks in coverage. If a format silently stops being readable, the
organiser goes back to guessing - which is exactly what we do not want.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from organizer.textract import extract  # noqa: E402

TMP = Path(__file__).parent / "_textract_tmp"


def _reset() -> None:
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True, exist_ok=True)


def _odt_with(text: str) -> Path:
    p = TMP / "note.odt"
    xml = (f'<?xml version="1.0"?><office:document-content>'
           f'<text:p>{text}</text:p></office:document-content>')
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("content.xml", xml)
    return p


def _docx_with(text: str) -> Path:
    p = TMP / "letter.docx"
    xml = f'<w:document><w:p><w:t>{text}</w:t></w:p></w:document>'
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return p


def _legacy_doc_with(text: str) -> Path:
    """Old .doc = OLE container with UTF-16 text runs inside."""
    p = TMP / "old.doc"
    blob = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512
    blob += text.encode("utf-16-le")
    blob += b"\x00" * 256
    p.write_bytes(blob)
    return p


def test_odt_is_read():
    _reset()
    t = extract(_odt_with("Quarterly budget review for the engineering team"))
    assert "Quarterly budget" in t, t


def test_docx_is_read():
    _reset()
    t = extract(_docx_with("Rental agreement between landlord and tenant"))
    assert "Rental agreement" in t, t


def test_old_doc_is_read_not_skipped():
    _reset()
    t = extract(_legacy_doc_with("Chapter 2 pointers and memory allocation"))
    assert "pointers" in t.lower(), t


def test_plain_text_is_read():
    _reset()
    p = TMP / "notes.txt"
    p.write_text("Invoice for consulting work, due April", encoding="utf-8")
    assert "Invoice" in extract(p)


def test_code_file_is_read():
    _reset()
    p = TMP / "app.py"
    p.write_text("def classify_receipt(path):\n    return 'invoice'", encoding="utf-8")
    assert "classify_receipt" in extract(p)


def test_binary_garbage_never_crashes_or_invents_text():
    _reset()
    p = TMP / "blob.bin"
    p.write_bytes(bytes(range(256)) * 20)
    # unknown extension: not claimed as readable, returns ""
    assert extract(p) == ""


def test_missing_file_is_safe():
    assert extract(TMP / "does_not_exist.pdf") == ""


if __name__ == "__main__":
    failures = 0
    try:
        for name, fn in sorted(globals().items()):
            if name.startswith("test_") and callable(fn):
                try:
                    fn()
                    print(f"  ok   {name}")
                except AssertionError as exc:
                    failures += 1
                    print(f"  FAIL {name}: {exc}")
    finally:
        import shutil
        shutil.rmtree(TMP, ignore_errors=True)
    print("\nall good" if not failures else f"\n{failures} failed")
    sys.exit(1 if failures else 0)
