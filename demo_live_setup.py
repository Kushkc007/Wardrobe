"""Build a safe, disposable dataset for the live dashboard demo.

Creates demo_live/ with its own config, family profile, Inbox and Vault so the
presentation never touches real family files.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEMO = ROOT / "demo_live"
INBOX = DEMO / "Inbox"
VAULT = DEMO / "Organized"


def write(rel: str, data: bytes = b"demo") -> None:
    p = INBOX / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def main() -> None:
    if DEMO.exists():
        shutil.rmtree(DEMO)
    INBOX.mkdir(parents=True)
    VAULT.mkdir(parents=True)

    # Documents
    write("Aru_Resume.pdf", b"resume demo " * 200)
    write("Papa_Resume.pdf", b"father resume demo " * 100)
    write("Aru_Acme_SalarySlip_Aug.pdf", b"salary demo")
    write("Papa_Skyline_SalarySlip_Jul.pdf", b"salary demo father")
    write("Scans/Papa_Aadhaar.pdf", b"aadhaar demo")
    write("Aru_PAN_Card.pdf", b"pan demo")
    write("signature_aru.pdf", b"signature demo")
    write("Papa_Property_Papers.pdf", b"property demo")
    write("Aru_Blue_Award_2025.pdf", b"award demo")
    write("Papa_Skyline_Site_Report.xlsx", b"site report demo")
    write("Aru_Rent_Agreement_2024.pdf", b"rent agreement demo")

    # Photos
    write("Aru_Goa_Trip_Beach.jpg", b"jpeg demo")
    write("Aru_wedding_haldi.jpg", b"jpeg demo")
    write("sunset_beach.jpg", b"jpeg demo")

    # Shared
    write("Atomic_Habits.epub", b"epub demo")
    write("passwords.txt", b"gmail: demo")
    write("Screenshot_2024.png", b"png demo")
    write("good_morning.jpg", b"jpeg demo")
    write("meme_monday.png", b"png demo")

    # Unknown, nested and duplicate
    write("random_notes.pdf", b"random demo")
    write("Old/Docs/unknown_project_brief.pdf", b"unknown brief")
    write("Aru_Resume_copy.pdf", b"resume demo " * 200)

    cfg = f'''[general]
vault = "{VAULT.as_posix()}"
roots = ["{INBOX.as_posix()}"]
min_file_age_hours = 0
max_size_mb = 512
confidence_threshold = 0.55
recursive = true
max_depth = 8
people = ["Aarav", "Raghav"]
person_first_layout = true
family_layout = true
detect_duplicates = true
duplicate_folder = "Others"
separate_whatsapp_junk = false
enable_face_recognition = false
dynamic_context_folders = true

[layout]
pattern = "{{category}}/{{subcategory}}/{{filename}}"
'''
    (DEMO / "config.toml").write_text(cfg, encoding="utf-8")
    (DEMO / "family.json").write_text('''{
  "version": 1,
  "enabled": true,
  "people": [
    {"name": "Aarav", "relationship": "self", "aliases": ["Aru"], "companies": ["Acme", "Orbit"]},
    {"name": "Raghav", "relationship": "Father", "aliases": ["Papa"], "companies": ["Skyline"]}
  ],
  "rules": []
}
''', encoding="utf-8")
    print(f"Demo ready: {DEMO}")
    print(f"  Inbox : {INBOX}")
    print(f"  Vault : {VAULT}")
    print(f"  Config: {DEMO / 'config.toml'}")


if __name__ == "__main__":
    main()
