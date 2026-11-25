"""Image understanding tests: provenance beats file extension."""
from __future__ import annotations

import json
import sys
import tomllib
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
THRESHOLD = CONFIG["general"]["confidence_threshold"]
ENGINE = RuleEngine(TAXONOMY, CONFIG.get("fallback", {}))


def photo(name: str, hints: list[str], text: str = "", rel_dir: str = "Pictures"):
    f = FileInfo(
        id="t", path=f"C:/x/{name}", root="C:/x", rel_dir=rel_dir, name=name,
        ext=Path(name).suffix.lower(), size=1, mtime=0.0, kind="Image",
        text=text, text_chars=len(text), hints=hints,
    )
    v = ENGINE.classify(f)
    if v.confidence < THRESHOLD:
        return "Unsorted", "Needs Review", v
    return v.category, v.subcategory, v


def test_screenshot_goes_to_screenshots():
    cat, sub, v = photo("Screenshot 2024-03-01 101010.png", ["screenshot"])
    assert sub == "Screenshots", v


def test_camera_photo_is_a_photo_not_a_screenshot():
    cat, sub, v = photo(
        "IMG_3301.jpg",
        ["photo", "camera"],
        "photograph taken with Apple iPhone 13 taken 2023:04:02",
    )
    assert sub == "Photos", v


def test_oem_wallpaper_is_not_filed_as_a_personal_photo():
    # The exact files that were misfiled before image reading existed.
    cat, sub, v = photo(
        "2022_Acer_Consumer_OLED_Default_3840x2400.jpg",
        ["wallpaper", "art"],
        "stock artwork or desktop wallpaper 3840x2400 landscape 9.2 megapixels",
    )
    assert sub == "Wallpapers & Art", v


def test_raw_image_with_no_evidence_still_lands_somewhere_sane():
    cat, sub, v = photo("qzlkjhgf.png", [])
    assert cat == "Media Library", v


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
