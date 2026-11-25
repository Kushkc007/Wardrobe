"""Books and saved doc sets must move as ONE unit, never page by page."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from organizer.rules import RuleEngine  # noqa: E402
from organizer.scanner import FileInfo, _bundle_kind  # noqa: E402

TAXONOMY = json.loads((ROOT / "taxonomy.json").read_text(encoding="utf-8"))
ENGINE = RuleEngine(TAXONOMY, {})


class FakeCfg:
    ignore_dirs = set()


def _make_book(root: Path, pages: int = 20) -> Path:
    book = root / "Big Book"
    book.mkdir(parents=True)
    for i in range(pages):
        (book / f"page{i}.html").write_text("<html>chapter</html>", encoding="utf-8")
    (book / "style.css").write_text("body{}", encoding="utf-8")
    for i in range(pages):
        (book / f"img{i}.png").write_bytes(b"\x89PNG")
    return book


def test_folder_of_pages_is_a_bundle(tmp=Path(__file__).parent / "_bundle_tmp"):
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        book = _make_book(tmp)
        kind = _bundle_kind(book, FakeCfg())
        assert "bundle" in kind.lower(), kind
    finally:
        _cleanup(tmp)


def test_a_normal_folder_is_not_a_bundle(tmp=Path(__file__).parent / "_plain_tmp"):
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        plain = tmp / "Docs"
        plain.mkdir(exist_ok=True)
        (plain / "a.pdf").write_bytes(b"%PDF-1.4")
        (plain / "b.pdf").write_bytes(b"%PDF-1.4")
        assert _bundle_kind(plain, FakeCfg()) == ""
    finally:
        _cleanup(tmp)


def test_bundle_is_classified_as_a_book_not_code():
    f = FileInfo(
        id="b", path="C:/x/Java in Depth", root="C:/x", rel_dir="books",
        name="Java in Depth", ext="", size=1, mtime=0.0,
        kind="Document bundle", text="Java in Depth document bundle ebook book",
        text_chars=60, is_dir=True, item_count=40,
    )
    v = ENGINE.classify(f)
    assert v.category == "Learning & Reference", v
    assert v.subcategory == "Books & Ebooks", v


def test_code_repo_still_stays_a_repo():
    f = FileInfo(
        id="r", path="C:/x/app", root="C:/x", rel_dir="", name="app",
        ext="", size=1, mtime=0.0, kind="Project folder",
        text="app package.json project folder repository", text_chars=40,
        is_dir=True, item_count=12,
    )
    v = ENGINE.classify(f)
    assert v.subcategory == "Projects & Repos", v


def _cleanup(p: Path):
    import shutil
    shutil.rmtree(p, ignore_errors=True)


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
