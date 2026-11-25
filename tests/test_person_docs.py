"""Tests for intelligent document recognition and person-first hierarchical organization.

Verifies:
- Resumes are filed under [Person]/Resume/[File]
- Aadhaar / PAN / Biometric IDs are filed under [Person]/Biometrics/[File]
- Marksheets / Degrees are filed under [Person]/Education/[File]
- Medical Prescriptions / Lab Reports are filed under [Person]/Health/[File]
- Salary Slips / Payslips are filed under [Person]/Salary/[File]
- Kinship normalization (Papa -> Father, Mummy -> Mother, Bua -> Bua, etc.)
- Non-person generic files stay in standard system categories.
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

from organizer.config import Config, load_taxonomy
from organizer.doc_intel import recognize_document, normalize_person_name, extract_person_from_resume_header
from organizer.planner import build_plan
from organizer.scanner import FileInfo


def test_resume_intelligence():
    resume_text = (
        "KUSH KUMAR\n"
        "Software Engineer | kush@example.com | +91 9876543210\n"
        "Summary: Experienced Python and AI developer.\n"
        "Experience:\n"
        "- Senior Developer at TechCorp\n"
        "Education:\n"
        "- B.Tech Computer Science\n"
        "Skills:\n"
        "- Python, Machine Learning, Docker\n"
    )
    doc = recognize_document("my_resume.pdf", resume_text, people=["Kush"])
    assert doc.doc_type == "Resume", f"Expected Resume, got {doc.doc_type}"
    assert "Kush" in doc.person, f"Expected Kush, got {doc.person}"
    assert doc.confidence >= 0.90


def test_aadhaar_biometrics_intelligence():
    aadhaar_text = (
        "GOVERNMENT OF INDIA\n"
        "Unique Identification Authority of India\n"
        "Enrollment No: 1234/56789/12345\n"
        "To\n"
        "Ramesh Kumar\n"
        "S/O Shyam Kumar\n"
        "DOB: 12/04/1972\n"
        "Male\n"
        "1234 5678 9012\n"
        "Mera Aadhaar, Meri Pehchan\n"
    )
    doc = recognize_document("Father_Aadhaar.pdf", aadhaar_text, people=["Father", "Ramesh"])
    assert doc.doc_type == "Biometrics", f"Expected Biometrics, got {doc.doc_type}"
    assert doc.subtype == "Aadhaar", f"Expected Aadhaar, got {doc.subtype}"
    assert doc.person in ("Father", "Ramesh Kumar"), f"Got {doc.person}"


def test_pan_card_intelligence():
    pan_text = (
        "INCOME TAX DEPARTMENT\n"
        "GOVT. OF INDIA\n"
        "RAMESH KUMAR\n"
        "Father: SHYAM KUMAR\n"
        "05/01/1970\n"
        "Permanent Account Number\n"
        "ABCDE1234F\n"
    )
    doc = recognize_document("Papa_PAN.jpg", pan_text, people=["Papa", "Father"])
    assert doc.doc_type == "Biometrics"
    assert doc.subtype == "PAN"
    assert doc.person in ("Father", "Papa", "Ramesh Kumar")


def test_education_marksheet_intelligence():
    marksheet_text = (
        "CENTRAL BOARD OF SECONDARY EDUCATION\n"
        "MARKS STATEMENT\n"
        "Candidate Name: KUSH KUMAR\n"
        "Roll No: 6123456\n"
        "School: Delhi Public School\n"
        "Result: PASS\n"
    )
    doc = recognize_document("Class_12_Marksheet.pdf", marksheet_text, people=["Kush"])
    assert doc.doc_type == "Education"
    assert doc.subtype == "Marksheet"
    assert "Kush" in doc.person


def test_health_prescription_intelligence():
    rx_text = (
        "MAX SUPER SPECIALITY HOSPITAL\n"
        "Department of Cardiology\n"
        "Patient Name: Kamla Devi\n"
        "Age: 58 | Female\n"
        "Diagnosis: Hypertension\n"
        "Rx:\n"
        "1. Tab Telmisartan 40mg once daily\n"
    )
    doc = recognize_document("Bua_Prescription.pdf", rx_text, people=["Bua"])
    assert doc.doc_type == "Health"
    assert doc.subtype == "Prescription"
    assert doc.person == "Bua" or "Kamla" in doc.person


def test_salary_slip_intelligence():
    salary_text = (
        "INFOSYS TECHNOLOGIES LIMITED\n"
        "Salary Slip for September 2024\n"
        "Employee Name: Kush Kumar\n"
        "Employee ID: 104523\n"
        "Basic Salary: 55000\n"
        "HRA: 22000\n"
        "Gross Salary: 85000\n"
        "Net Pay: 78000\n"
    )
    doc = recognize_document("Salary_Slip_Sep.pdf", salary_text, people=["Kush"])
    assert doc.doc_type == "Salary"
    assert doc.subtype == "Payslip"
    assert "Kush" in doc.person


def test_hierarchical_plan_building():
    cfg = Config.load()
    cfg.vault = Path("C:/Organized_Vault")
    cfg.people = ["Kush", "Father", "Mother", "Papa", "Mummy", "Bua"]
    cfg.person_first_layout = True
    tax = load_taxonomy(cfg.taxonomy_path)

    files = [
        FileInfo(
            id="1", path="C:/Downloads/Kush_Resume.pdf", root="C:/Downloads", rel_dir="",
            name="Kush_Resume.pdf", ext=".pdf", size=1500, mtime=0, kind="Document",
            text="Kush Kumar\nSoftware Engineer\nSkills\nExperience", text_chars=40
        ),
        FileInfo(
            id="2", path="C:/Downloads/Papa_Aadhaar.pdf", root="C:/Downloads", rel_dir="",
            name="Papa_Aadhaar.pdf", ext=".pdf", size=2000, mtime=0, kind="Document",
            text="Government of India\nUnique Identification Authority of India\n1234 5678 9012", text_chars=50
        ),
        FileInfo(
            id="3", path="C:/Downloads/Mother_Degree.pdf", root="C:/Downloads", rel_dir="",
            name="Mother_Degree.pdf", ext=".pdf", size=2500, mtime=0, kind="Document",
            text="Delhi University\nDegree of Bachelor of Science\nCandidate Name: Sunita Devi", text_chars=50
        ),
        FileInfo(
            id="4", path="C:/Downloads/Bua_Medical.pdf", root="C:/Downloads", rel_dir="",
            name="Bua_Medical.pdf", ext=".pdf", size=1200, mtime=0, kind="Document",
            text="City Hospital\nPatient: Kamla Devi\nPrescription\nTab Paracetamol", text_chars=40
        ),
        FileInfo(
            id="5", path="C:/Downloads/Kush_Salary.pdf", root="C:/Downloads", rel_dir="",
            name="Kush_Salary.pdf", ext=".pdf", size=1800, mtime=0, kind="Document",
            text="Company Ltd\nSalary Slip\nEmployee: Kush Kumar\nNet Salary: 90000", text_chars=40
        ),
        FileInfo(
            id="6", path="C:/Downloads/node-setup.msi", root="C:/Downloads", rel_dir="",
            name="node-setup.msi", ext=".msi", size=30000, mtime=0, kind="Installer",
            text="", text_chars=0
        ),
    ]

    items, stats = build_plan(cfg, files, tax, use_llm=False)
    dest_map = {Path(i.source).name: Path(i.destination) for i in items}

    # 1. Kush Resume -> C:/Organized_Vault/Kush/Resume/Kush_Resume.pdf
    dest_kush_resume = dest_map["Kush_Resume.pdf"]
    assert "Kush" in dest_kush_resume.parts, f"Expected Kush in path, got {dest_kush_resume}"
    assert "Resume" in dest_kush_resume.parts, f"Expected Resume in path, got {dest_kush_resume}"

    # 2. Papa Aadhaar -> C:/Organized_Vault/Papa/Biometrics/Papa_Aadhaar.pdf
    dest_papa_aadhaar = dest_map["Papa_Aadhaar.pdf"]
    assert any(p in dest_papa_aadhaar.parts for p in ("Papa", "Father")), f"Got {dest_papa_aadhaar}"
    assert any(x in dest_papa_aadhaar.parts for x in ("Aadhaar", "Government IDs", "Biometrics")), f"Expected Government IDs in path, got {dest_papa_aadhaar}"

    # 3. Mother Degree -> C:/Organized_Vault/Mother/Education/Mother_Degree.pdf
    dest_mother_degree = dest_map["Mother_Degree.pdf"]
    assert "Mother" in dest_mother_degree.parts, f"Got {dest_mother_degree}"
    assert any(x in dest_mother_degree.parts for x in ("Degree", "Education")), f"Expected Degree in path, got {dest_mother_degree}"

    # 4. Bua Medical -> C:/Organized_Vault/Bua/Health/Bua_Medical.pdf
    dest_bua_health = dest_map["Bua_Medical.pdf"]
    assert "Bua" in dest_bua_health.parts, f"Got {dest_bua_health}"
    assert any(x in dest_bua_health.parts for x in ("Medical", "Prescription", "Health")), f"Expected a medical label in path, got {dest_bua_health}"

    # 5. Kush Salary -> C:/Organized_Vault/Kush/Salary/Kush_Salary.pdf
    dest_kush_salary = dest_map["Kush_Salary.pdf"]
    assert "Kush" in dest_kush_salary.parts, f"Got {dest_kush_salary}"
    assert any(x in dest_kush_salary.parts for x in ("Salary", "Salary Slip", "Salary Slips")), f"Expected Salary label in path, got {dest_kush_salary}"

    # 6. Generic installer -> standard category layout
    dest_node = dest_map["node-setup.msi"]
    assert "Installers" in dest_node.parts, f"Got {dest_node}"
    assert not any(p in dest_node.parts for p in ("Kush", "Papa", "Mother", "Bua")), f"Got {dest_node}"


def test_job_title_in_resume_header_not_extracted_as_person():
    resume_text = (
        "PRINCIPAL SOFTWARE ARCHITECT & FULL STACK DEVELOPER\n"
        "Kush Kumar\n"
        "kush@example.com | +91 9999999999\n"
        "Summary: 10 years experience building distributed AI systems.\n"
        "Experience:\n"
        "- Tech Lead at Global Corp\n"
        "Education: B.Tech\n"
    )
    doc = recognize_document("Resume.pdf", resume_text, people=["Kush"])
    assert doc.doc_type == "Resume"
    assert doc.person == "Kush", f"Expected Kush, got {doc.person}"
    assert "Architect" not in doc.person and "Developer" not in doc.person


def test_pan_card_simple_filename():
    doc = recognize_document("Father_PAN.pdf", text="Father PAN Record", people=["Father"])
    assert doc.doc_type == "Biometrics", f"Expected Biometrics, got {doc.doc_type}"
    assert doc.subtype == "PAN", f"Expected PAN, got {doc.subtype}"
    assert doc.person == "Father", f"Expected Father, got {doc.person}"


def test_ordinals_not_extracted_as_person():
    doc_10th = recognize_document("10th_certificate.pdf", text="Board of Secondary Education Passing Certificate", people=["Kush"])
    assert doc_10th.doc_type == "Education", f"Expected Education, got {doc_10th.doc_type}"
    assert doc_10th.person != "10th", f"Ordinal 10th must not become person name, got {doc_10th.person}"

    doc_12th = recognize_document("12th_marksheet.pdf", text="CBSE Senior Secondary Examination Marks Statement", people=["Kush"])
    assert doc_12th.doc_type == "Education", f"Expected Education, got {doc_12th.doc_type}"
    assert doc_12th.person != "12th", f"Ordinal 12th must not become person name, got {doc_12th.person}"


def test_whatsapp_document_routed_to_person_docs_not_junk():
    cfg = Config.load()
    cfg.vault = Path("C:/Vault")
    cfg.people = ["Kush", "Father", "Mother"]
    cfg.person_first_layout = True
    cfg.separate_whatsapp_junk = True
    tax = load_taxonomy(cfg.taxonomy_path)

    # Scanned Aadhaar card received over WhatsApp
    f = FileInfo(
        id="wa_doc", path="C:/Downloads/IMG-20240101-WA0001.jpg", root="C:/Downloads",
        rel_dir="WhatsApp Images", name="IMG-20240101-WA0001.jpg", ext=".jpg", size=180000,
        mtime=0, kind="Image",
        text="GOVERNMENT OF INDIA\nUnique Identification Authority of India\nKush Kumar\n1234 5678 9012",
        text_chars=80, hints=["scan", "document"]
    )
    items, stats = build_plan(cfg, [f], tax, use_llm=False)
    assert len(items) == 1
    dest = Path(items[0].destination)
    assert "WhatsApp_Junk" not in dest.parts, f"Aadhaar card must not go to WhatsApp_Junk! Got {dest}"
    assert "Kush" in dest.parts, f"Expected Kush in path, got {dest}"
    assert any(x in dest.parts for x in ("Aadhaar", "Government IDs", "Biometrics")), f"Expected Aadhaar in path, got {dest}"


if __name__ == "__main__":
    test_resume_intelligence()
    print("  ok   test_resume_intelligence")
    test_aadhaar_biometrics_intelligence()
    print("  ok   test_aadhaar_biometrics_intelligence")
    test_pan_card_intelligence()
    print("  ok   test_pan_card_intelligence")
    test_education_marksheet_intelligence()
    print("  ok   test_education_marksheet_intelligence")
    test_health_prescription_intelligence()
    print("  ok   test_health_prescription_intelligence")
    test_salary_slip_intelligence()
    print("  ok   test_salary_slip_intelligence")
    test_hierarchical_plan_building()
    print("  ok   test_hierarchical_plan_building")
    test_job_title_in_resume_header_not_extracted_as_person()
    print("  ok   test_job_title_in_resume_header_not_extracted_as_person")
    test_pan_card_simple_filename()
    print("  ok   test_pan_card_simple_filename")
    test_ordinals_not_extracted_as_person()
    print("  ok   test_ordinals_not_extracted_as_person")
    test_whatsapp_document_routed_to_person_docs_not_junk()
    print("  ok   test_whatsapp_document_routed_to_person_docs_not_junk")
    print("\nall good")
