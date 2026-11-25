"""End-to-end demo of on-the-spot folder learning.

Creates a fake "Downloads_X" folder with sample family files, runs the real
scan -> plan -> apply pipeline, and prints the resulting tree.

Nothing here uses real personal data. Run:

    python demo_family_sort.py
"""
from __future__ import annotations

import contextlib
import io
import shutil
from pathlib import Path

from organizer.apply import apply_plan
from organizer.config import Config, load_taxonomy
from organizer.family import save_profile
from organizer.planner import build_plan
from organizer.scanner import scan

ROOT = Path(__file__).resolve().parent
DEMO = ROOT / "demo_run"
SOURCE = DEMO / "Downloads_X"
VAULT = DEMO / "Organized"


def _write(name: str, data: bytes = b"demo") -> None:
    path = SOURCE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _make_files() -> None:
    # Documents
    _write("Aru_Resume.pdf", b"resume demo " * 200)
    _write("Papa_Resume.pdf", b"resume demo father")
    _write("Aru_Acme_SalarySlip_Aug.pdf", b"salary demo")
    _write("Papa_Skyline_SalarySlip_Jul.pdf", b"salary demo father")
    _write("Papa_Aadhaar.pdf", b"aadhaar demo")
    _write("Aru_PAN_Card.pdf", b"pan demo")
    _write("signature_aru.pdf", b"signature demo")
    _write("Papa_Property_Papers.pdf", b"property demo")
    _write("Aru_Blue_Award_2025.pdf", b"award demo")
    _write("Papa_Skyline_Site_Report.xlsx", b"site report demo")

    # Photos
    _write("Aru_Goa_Trip_Beach.jpg", b"jpeg demo")
    _write("Aru_wedding_haldi.jpg", b"jpeg demo")
    _write("sunset_beach.jpg", b"jpeg demo")

    # Shared / common
    _write("Atomic_Habits.epub", b"epub demo")
    _write("passwords.txt", b"gmail: demo")
    _write("Screenshot_2024.png", b"png demo")
    _write("good_morning.jpg", b"jpeg demo")
    _write("meme_monday.png", b"png demo")

    # Unknown + duplicate
    _write("random_notes.pdf", b"random demo")
    _write("Aru_Resume_copy.pdf", b"resume demo " * 200)  # same bytes as Aru_Resume.pdf


def _tree(root: Path, prefix: str = "") -> list[str]:
    lines: list[str] = []
    entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    for i, entry in enumerate(entries):
        last = i == len(entries) - 1
        lines.append(prefix + ("└── " if last else "├── ") + entry.name + ("/" if entry.is_dir() else ""))
        if entry.is_dir():
            lines.extend(_tree(entry, prefix + ("    " if last else "│   ")))
    return lines


def main() -> None:
    if DEMO.exists():
        shutil.rmtree(DEMO)
    SOURCE.mkdir(parents=True)

    cfg = Config()
    cfg.app_dir = DEMO
    cfg.vault = VAULT
    cfg.roots = [SOURCE]
    cfg.state_dir = DEMO / "state"
    cfg.report_dir = DEMO / "reports"
    cfg.family_profile_path = DEMO / "family.json"
    cfg.taxonomy_path = ROOT / "taxonomy.json"
    cfg.enable_face_recognition = False
    cfg.separate_whatsapp_junk = False
    cfg.min_file_age_hours = 0
    cfg.ensure_dirs()

    save_profile(cfg, {
        "people": [
            {"name": "Aarav", "relationship": "self", "aliases": ["Aru"], "companies": ["Acme", "Orbit"]},
            {"name": "Raghav", "relationship": "Father", "aliases": ["Papa"], "companies": ["Skyline"]},
        ]
    })
    cfg.people = ["Aarav", "Raghav"]

    _make_files()
    print("BEFORE — demo_run/Downloads_X")
    print("\n".join(_tree(SOURCE)))
    print()

    with contextlib.redirect_stderr(io.StringIO()):
        files, errors = scan(cfg)
    tax = load_taxonomy(cfg.taxonomy_path)
    items, stats = build_plan(cfg, files, tax, use_llm=False)
    result = apply_plan(cfg, items)

    print(f"Scanned {len(files)} files · planned {len(items)} · moved {result.moved} · duplicates {stats.get('duplicates', 0)}")
    if errors:
        print("scan warnings:", errors)
    print()
    print("AFTER — demo_run/Organized")
    print("\n".join(_tree(VAULT)))


if __name__ == "__main__":
    main()
