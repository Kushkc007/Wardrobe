"""Regression tests for the classifier.

These lock in the cases that actually went wrong on a real machine, so a future
tweak to the weights cannot quietly bring them back.

    python -m pytest tests -q      (or)      python tests\test_rules.py
"""
from __future__ import annotations

import json
import sys
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from organizer.rules import RuleEngine  # noqa: E402
from organizer.scanner import FileInfo  # noqa: E402

TAXONOMY = json.loads((ROOT / "taxonomy.json").read_text(encoding="utf-8"))
_CONFIG_FILE = ROOT / "config.toml"
if not _CONFIG_FILE.exists():
    _CONFIG_FILE = ROOT / "config.example.toml"
CONFIG = tomllib.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
FALLBACK = CONFIG.get("fallback", {})
THRESHOLD = CONFIG["general"]["confidence_threshold"]
ENGINE = RuleEngine(TAXONOMY, FALLBACK)


def filed(name: str, text: str = "", rel_dir: str = "", is_dir: bool = False):
    """Where does this file actually end up, after the review threshold?"""
    v = ENGINE.classify(make(name, text, rel_dir, is_dir))
    if v.confidence < THRESHOLD:
        return "Unsorted", "Needs Review", v
    return v.category, v.subcategory, v
def make(name: str, text: str = "", rel_dir: str = "", is_dir: bool = False) -> FileInfo:
    return FileInfo(
        id="t",
        path=f"C:/x/{name}",
        root="C:/x",
        rel_dir=rel_dir,
        name=name,
        ext=Path(name).suffix.lower(),
        size=1,
        mtime=0.0,
        kind="",
        text=text,
        text_chars=len(text),
        note="",
        is_dir=is_dir,
        item_count=0,
    )


def test_scattered_words_in_a_spreadsheet_do_not_decide_it():
    # The real bug: "install" appeared in one cell of a notes spreadsheet and
    # the whole file was filed under Installers & Software.
    text = "buy new laptop install windows later tax invoice idea"
    cat, sub, v = filed("Book1.xlsx", text)
    assert cat != "Installers & Software", v


def test_body_alone_never_clears_the_review_bar():
    # The name says nothing; only the contents do. That is a suggestion, and a
    # human should confirm it rather than have it silently filed.
    cat, sub, v = filed("scan001.txt", "tax invoice insurance loan salary")
    assert cat == "Unsorted", v


def test_filename_still_wins():
    cat, sub, v = filed("Docker Desktop Installer.exe")
    assert cat == "Installers & Software", v


def test_extension_beats_a_stray_filename_word():
    # A video named "invoice" is still a video, not paperwork.
    cat, sub, v = filed("invoice.mp4")
    assert cat == "Media Library", v


def test_real_document_by_name():
    cat, sub, v = filed("Form16_2024.pdf", "income tax return")
    assert cat == "Money & Paperwork", v


def test_repo_folder_is_a_project():
    cat, sub, v = filed("hypit", rel_dir="Repo\\hypit", is_dir=True)
    assert sub == "Projects & Repos", v


def test_unknown_file_goes_to_review():
    cat, sub, v = filed("qwertyuiop.xyz")
    assert cat == "Unsorted", v


def test_images_never_go_to_video():
    # Fix for user bug: JPGs or PNGs with video/vid/clip in name should never go to video
    cat, sub, v = filed("video_cover.jpg")
    assert "video" not in sub.lower() and "video" not in cat.lower(), v
    assert sub == "Photos" or cat == "Media Library", v

    cat, sub, v = filed("vid_123.jpg")
    assert "video" not in sub.lower(), v

    cat, sub, v = filed("clip_shot.png")
    assert "video" not in sub.lower(), v


def test_documents_never_go_to_video_or_zips():
    # Fix for user bug: Books/PDFs with "intro" or "archives" should not become YouTube or Zips
    cat, sub, v = filed("Intro to HTML.pdf")
    assert sub != "YouTube & Shorts", v
    assert sub == "Books & Ebooks", v

    cat, sub, v = filed("Introduction to Algorithms.pdf")
    assert sub == "Books & Ebooks", v

    cat, sub, v = filed("chip-archives-2006.pdf")
    assert sub != "Zips & Bundles", v


def test_resumes_and_certificates():
    cat, sub, v = filed("my_resume.pdf")
    assert sub == "Salary & Employment", v

    cat, sub, v = filed("degree_certificate.pdf")
    assert sub == "Identity & Certificates", v


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
