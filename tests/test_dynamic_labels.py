"""Folder names must be learned from the files, not from a fixed list."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from organizer.config import Config, load_taxonomy
from organizer.family import save_profile
from organizer.labels import LabelLearner
from organizer.planner import build_plan
from organizer.scanner import FileInfo


def _file(fid, name, text="", hints=None):
    ext = "." + name.rsplit(".", 1)[-1].lower()
    return FileInfo(
        id=fid, path=f"C:/Downloads/{name}", root="C:/Downloads", rel_dir="",
        name=name, ext=ext, size=100, mtime=0, kind="Document",
        text=text, text_chars=len(text), hints=hints or [],
    )


def test_label_comes_from_filename_not_a_predefined_category():
    learner = LabelLearner(people=["Alpha", "Beta", "Gamma"], companies=["R1"])
    cases = {
        "Alpha_Resume.pdf": "Resume",
        "Alpha_Aadhaar.pdf": "Aadhaar",
        "Alpha_R1_SalarySlip_Aug.pdf": "Salary Slip",
        "Alpha_Form16.pdf": "Form 16",
        "Alpha_Property_Papers.pdf": "Property Papers",
        "Alpha_Goa_Trip.jpg": "Goa Trip",
    }
    for i, (name, expected) in enumerate(cases.items()):
        learner.observe(str(i), name)
    learner.finalize()
    for i, (name, expected) in enumerate(cases.items()):
        assert learner.label_for(str(i)) == expected, (name, learner.label_for(str(i)))


def test_similar_labels_share_one_folder():
    learner = LabelLearner(people=["Alpha", "Beta", "Gamma"], companies=["R1"])
    learner.observe("a", "Alpha_Salary_Slip.pdf")
    learner.observe("b", "Beta_SalarySlips.pdf")
    learner.observe("c", "Gamma_salary_slip.pdf")
    learner.finalize()
    labels = {learner.label_for(i) for i in ("a", "b", "c")}
    assert labels == {"Salary Slip"}, labels


def test_camera_and_whatsapp_noise_is_not_a_folder():
    learner = LabelLearner(people=["Alpha", "Beta", "Gamma"], companies=["R1"])
    learner.observe("a", "IMG-20240101-WA0001.jpg", doc_info=None)
    learner.observe("b", "IMG_20240101_123456.jpg", doc_info=None)
    learner.finalize()
    assert learner.label_for("a") == ""
    assert learner.label_for("b") == ""


def test_new_folder_is_created_on_the_spot():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cfg = Config()
        cfg.app_dir = root
        cfg.vault = root / "Vault"
        cfg.state_dir = root / "state"
        cfg.report_dir = root / "reports"
        cfg.family_profile_path = root / "family.json"
        cfg.ensure_dirs()
        save_profile(cfg, {"people": [{"name": "Alpha", "aliases": ["Ali"]}]})
        cfg.people = ["Alpha"]
        tax = load_taxonomy(cfg.taxonomy_path)

        files = [
            _file("1", "Ali_Blue_Award_2025.pdf", "Blue Award certificate"),
            _file("2", "Ali_Blue_Award_2024.pdf", "Blue Award certificate"),
        ]
        items, _ = build_plan(cfg, files, tax, use_llm=False)
        for item in items:
            assert Path(item.destination).parent == cfg.vault / "Alpha" / "Blue Award"
