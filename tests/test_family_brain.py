"""Family Brain tests: user-defined people, dynamic folders, common buckets.

These tests describe the behaviour the family asked for:

    <Person>/Photos/Personal, .../With Others, .../Scenery,
    .../Functions/Wedding/Haldi, .../Trips/Amritsar
    <Person>/Documents/Resume, .../Salary Slips/<Company>,
    .../Government IDs/Aadhaar, .../Biometrics, .../Property
    Common/Books, Common/Passwords, Common/Screenshots,
    Common/Greetings/Good Morning, Common/Greetings/Good Night,
    Common/Jokes & Memes
    Others/... for anything that cannot be attributed safely
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from organizer.apply import apply_plan
from organizer.config import Config, load_taxonomy
from organizer.family import load_profile, save_profile
from organizer.planner import build_plan
from organizer.scanner import FileInfo


PEOPLE = [
    {"name": "Kushagra", "relationship": "self", "aliases": ["Kush"], "companies": ["R1", "Rubix"]},
    {"name": "Manoj Kumar Chaturvedi", "relationship": "Father",
     "aliases": ["Papa", "Manoj"], "companies": ["Mahagun", "Pragmatic", "Ugly Construction"]},
    {"name": "Govind Chaturvedi", "relationship": "Brother", "aliases": ["Govind"]},
    {"name": "Seema Devi", "relationship": "Mother", "aliases": ["Mummy"]},
]


def _cfg(tmp: Path) -> Config:
    cfg = Config()
    cfg.app_dir = tmp
    cfg.vault = tmp / "Vault"
    cfg.state_dir = tmp / "state"
    cfg.report_dir = tmp / "reports"
    cfg.family_profile_path = tmp / "family.json"
    cfg.ensure_dirs()
    save_profile(cfg, {"people": PEOPLE})
    cfg.people = [p["name"] for p in PEOPLE]
    return cfg


def _file(fid: str, name: str, text: str = "", ext: str | None = None,
          hints: list[str] | None = None, size: int = 2048,
          path: str | None = None) -> FileInfo:
    ext = ext or ("." + name.rsplit(".", 1)[-1].lower())
    return FileInfo(
        id=fid, path=path or f"C:/Downloads/{name}", root="C:/Downloads", rel_dir="",
        name=name, ext=ext, size=size, mtime=0, kind="Document",
        text=text, text_chars=len(text), hints=hints or [],
    )


def _dest(items, cfg, filename):
    for item in items:
        if Path(item.source).name == filename:
            return Path(item.destination).relative_to(cfg.vault)
    raise AssertionError(f"{filename} missing from plan")


def test_person_documents_and_dynamic_companies():
    with tempfile.TemporaryDirectory() as td:
        cfg = _cfg(Path(td))
        tax = load_taxonomy(cfg.taxonomy_path)
        files = [
            _file("1", "Kush_Resume.pdf", "Kushagra\nSoftware Engineer\nSkills\nExperience"),
            _file("2", "Papa_Resume.pdf", "Manoj Kumar Chaturvedi\nElectrical Engineer\nSkills\nExperience"),
            _file("3", "Kush_R1_SalarySlip_Aug.pdf",
                  "R1 Technologies\nSalary Slip\nEmployee: Kushagra\nNet Salary 90000"),
            _file("4", "Papa_Aadhaar.pdf",
                  "Government of India\nUnique Identification Authority of India\n1234 5678 9012"),
            _file("5", "signature_kush.png", "", hints=["scan", "document"]),
            _file("6", "property_papers_papa.pdf", "Sale Deed\nProperty Registry\nRegistration"),
            _file("7", "Manoj_Mahagun_Site_Report.xlsx", "Mahagun site electrical work"),
        ]
        items, stats = build_plan(cfg, files, tax, use_llm=False)

        assert _dest(items, cfg, "Kush_Resume.pdf") == \
            Path("Kushagra/Resume/Kush_Resume.pdf")
        assert _dest(items, cfg, "Papa_Resume.pdf") == \
            Path("Manoj Kumar Chaturvedi/Resume/Papa_Resume.pdf")
        assert _dest(items, cfg, "Kush_R1_SalarySlip_Aug.pdf") == \
            Path("Kushagra/Salary Slip/R1/Kush_R1_SalarySlip_Aug.pdf")
        assert _dest(items, cfg, "Papa_Aadhaar.pdf") == \
            Path("Manoj Kumar Chaturvedi/Aadhaar/Papa_Aadhaar.pdf")
        assert _dest(items, cfg, "signature_kush.png") == \
            Path("Kushagra/Signature/signature_kush.png")
        assert _dest(items, cfg, "property_papers_papa.pdf") == \
            Path("Manoj Kumar Chaturvedi/Property Papers/property_papers_papa.pdf")
        assert _dest(items, cfg, "Manoj_Mahagun_Site_Report.xlsx") == \
            Path("Manoj Kumar Chaturvedi/Site Report/Mahagun/Manoj_Mahagun_Site_Report.xlsx")


def test_photo_folders_and_common_material():
    with tempfile.TemporaryDirectory() as td:
        cfg = _cfg(Path(td))
        tax = load_taxonomy(cfg.taxonomy_path)
        files = [
            _file("1", "Kush_portrait.jpg", "photograph taken with iPhone", hints=["photo", "camera"]),
            _file("2", "family_group.jpg", "photograph taken with iPhone", hints=["photo", "camera"]),
            _file("3", "sunset_beach.jpg", "", hints=["photo", "camera"]),
            _file("4", "Kush_wedding_haldi.jpg", "", hints=["photo", "camera"]),
            _file("5", "Kush_Amritsar_trip.jpg", "", hints=["photo", "camera"]),
            _file("6", "Atomic_Habits.epub", "", ext=".epub"),
            _file("7", "passwords.txt", "gmail: example"),
            _file("8", "Screenshot_2024.png", "", hints=["screenshot"]),
            _file("9", "good_morning.jpg", "", hints=["photo"]),
            _file("10", "good_night.jpg", "", hints=["photo"]),
            _file("11", "meme_monday.png", "", hints=["photo"]),
            _file("12", "stranger_notes.pdf", "completely unrelated text"),
        ]
        items, stats = build_plan(cfg, files, tax, use_llm=False)

        assert _dest(items, cfg, "Kush_portrait.jpg") == Path("Kushagra/Photos/Personal/Kush_portrait.jpg")
        assert _dest(items, cfg, "family_group.jpg") == Path("Common/Photos/With Others/family_group.jpg")
        assert _dest(items, cfg, "sunset_beach.jpg") == Path("Common/Photos/Scenery/sunset_beach.jpg")
        assert _dest(items, cfg, "Kush_wedding_haldi.jpg") == \
            Path("Kushagra/Photos/Functions/Wedding/Haldi/Kush_wedding_haldi.jpg")
        assert _dest(items, cfg, "Kush_Amritsar_trip.jpg") == \
            Path("Kushagra/Photos/Trips/Amritsar/Kush_Amritsar_trip.jpg")
        assert _dest(items, cfg, "Atomic_Habits.epub") == Path("Common/Books/Atomic Habits/Atomic_Habits.epub")
        assert _dest(items, cfg, "passwords.txt") == Path("Common/Passwords/passwords.txt")
        assert _dest(items, cfg, "Screenshot_2024.png") == Path("Common/Screenshots/Screenshot_2024.png")
        assert _dest(items, cfg, "good_morning.jpg") == Path("Common/Greetings/Good Morning/good_morning.jpg")
        assert _dest(items, cfg, "good_night.jpg") == Path("Common/Greetings/Good Night/good_night.jpg")
        assert _dest(items, cfg, "meme_monday.png") == Path("Common/Jokes & Memes/meme_monday.png")
        assert "Others" in _dest(items, cfg, "stranger_notes.pdf").parts


def test_user_rule_overrides_and_aliases():
    with tempfile.TemporaryDirectory() as td:
        cfg = _cfg(Path(td))
        tax = load_taxonomy(cfg.taxonomy_path)
        save_profile(cfg, {
            "people": PEOPLE,
            "rules": [{
                "match": ["mahagun", "invoice"],
                "person": "Manoj Kumar Chaturvedi",
                "path": ["Documents", "Job", "Mahagun", "Invoices"],
            }],
        })
        files = [_file("1", "Mahagun_invoice_march.pdf", "site work invoice")]
        items, _ = build_plan(cfg, files, tax, use_llm=False)
        assert _dest(items, cfg, "Mahagun_invoice_march.pdf") == \
            Path("Manoj Kumar Chaturvedi/Documents/Job/Mahagun/Invoices/Mahagun_invoice_march.pdf")


def test_duplicate_content_is_parked_without_loss():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cfg = _cfg(root)
        tax = load_taxonomy(cfg.taxonomy_path)
        src = root / "src"
        src.mkdir()
        a = src / "Kush_resume.pdf"
        b = src / "Kush_resume_copy.pdf"
        a.write_bytes(b"same content " * 200)
        b.write_bytes(b"same content " * 200)
        files = []
        for i, p in enumerate((a, b)):
            files.append(_file(str(i), p.name, "Kushagra\nSkills\nExperience",
                               ext=".pdf", size=p.stat().st_size, path=str(p)))
        items, stats = build_plan(cfg, files, tax, use_llm=False)
        assert stats["duplicates"] == 1
        dup = [i for i in items if i.status == "duplicate"][0]
        assert "Others" in Path(dup.destination).parts
        assert "Duplicates" in Path(dup.destination).parts
        assert dup.duplicate_of


def test_apply_creates_dynamic_folders_on_the_spot():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cfg = _cfg(root)
        tax = load_taxonomy(cfg.taxonomy_path)
        src = root / "src"
        src.mkdir()
        p = src / "Papa_Mahagun_Site_Report.pdf"
        p.write_text("Mahagun site report", encoding="utf-8")
        f = _file("1", p.name, "Mahagun site report", size=p.stat().st_size, path=str(p))
        items, _ = build_plan(cfg, [f], tax, use_llm=False)
        result = apply_plan(cfg, items)
        assert result.moved == 1, result.errors
        expected = cfg.vault / "Manoj Kumar Chaturvedi" / "Site Report" / "Mahagun" / p.name
        assert expected.exists(), f"expected {expected}"


def test_profile_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        cfg = _cfg(Path(td))
        profile = load_profile(cfg)
        assert profile.people[0].name == "Kushagra"
        assert profile.resolve("papa").name == "Manoj Kumar Chaturvedi"
        assert profile.resolve("Kush").name == "Kushagra"
