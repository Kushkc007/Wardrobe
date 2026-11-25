"""Tests for dynamic on-the-spot contextual folder creation.

Verifies:
- NASA folders are dynamically created on the spot from file details (e.g. NASA/James_Webb_Space_Telescope, NASA/Apollo_11, NASA/Mars_Rover)
  rather than being constrained to rigid static categories.
- Discovered projects like 'Cinri Health API' dynamically create exact contextual folders.
- Office work topics like 'Father/Office_Work/Vendor_Invoices_Q3' dynamically create exact contextual folder hierarchies.
- Specific academic subjects like 'Machine_Learning_Transformers' and 'Organic_Chemistry' dynamically create exact contextual folders.
- Dynamic topic extraction works from filenames, delimited titles, and document content.
- Integration with RuleEngine, recognize_document, and build_plan.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from organizer.config import Config, load_taxonomy
from organizer.doc_intel import (
    recognize_document, extract_contextual_topic, ContextTopicInfo
)
from organizer.planner import build_plan
from organizer.rules import RuleEngine
from organizer.scanner import FileInfo


def test_nasa_dynamic_folder_from_filename():
    # JWST
    doc_jwst = recognize_document("NASA_JWST_Optical_Design.pdf")
    assert doc_jwst.topic == "NASA", f"Expected NASA, got {doc_jwst.topic}"
    assert "James_Webb_Space_Telescope" in doc_jwst.context_path
    assert doc_jwst.confidence >= 0.90

    # Apollo 11
    doc_apollo = recognize_document("Apollo_11_Flight_Plan.pdf")
    assert doc_apollo.topic == "NASA"
    assert "Apollo_11" in doc_apollo.context_path

    # Mars Rover
    doc_rover = recognize_document("NASA_Mars_Rover_Telemetry.pdf")
    assert doc_rover.topic == "NASA"
    assert "Mars_Rover" in doc_rover.context_path

    # Structured delimited filename
    doc_delimited = recognize_document("NASA - James Webb Space Telescope - Calibration.pdf")
    assert doc_delimited.topic == "NASA"
    assert "James_Webb_Space_Telescope" in doc_delimited.context_path


def test_nasa_dynamic_folder_from_content():
    # Generic filename, but content specifies NASA and Mars Rover
    text = (
        "National Aeronautics and Space Administration\n"
        "Goddard Space Flight Center\n"
        "Curiosity Rover Science Operations\n"
        "Mars Rover Environmental Monitoring Station Report"
    )
    doc = recognize_document("report_doc_049.pdf", text=text)
    assert doc.topic == "NASA", f"Expected NASA, got {doc.topic}"
    assert "Mars_Rover" in doc.context_path or "James_Webb_Space_Telescope" in doc.context_path or "NASA" in doc.context_path


def test_cinri_health_api_project_creation():
    # Filename with project name
    doc1 = recognize_document("Cinri_Health_API_Specification.docx")
    assert doc1.topic == "Cinri_Health_API", f"Expected Cinri_Health_API, got {doc1.topic}"
    assert "Cinri_Health_API" in doc1.context_path
    assert doc1.confidence >= 0.90

    # From document content
    text = (
        "Cinri Health API Documentation\n"
        "Patient Ingestion Endpoints v2.1\n"
        "Authentication: Bearer Token required for all requests."
    )
    doc2 = recognize_document("endpoints_guide.pdf", text=text)
    assert doc2.topic == "Cinri_Health_API"
    assert "Cinri_Health_API" in doc2.context_path


def test_father_office_work_vendor_invoices_q3():
    # Person Father + Office Work + Vendor Invoices Q3
    doc = recognize_document(
        "Father_Office_Work_Vendor_Invoices_Q3.xlsx",
        people=["Father", "Kush"]
    )
    assert doc.person == "Father", f"Expected Father, got {doc.person}"
    assert doc.topic == "Office_Work", f"Expected Office_Work, got {doc.topic}"
    assert "Vendor_Invoices_Q3" in doc.context_path
    assert doc.context_path == ["Office_Work", "Vendor_Invoices_Q3"]


def test_machine_learning_transformers_subject():
    # Filename
    doc1 = recognize_document("Machine_Learning_Transformers_Attention.pdf")
    assert doc1.topic == "Machine_Learning_Transformers", f"Got {doc1.topic}"
    assert "Machine_Learning_Transformers" in doc1.context_path

    # From paper content (e.g. Attention Is All You Need)
    text = (
        "Attention Is All You Need\n"
        "Ashish Vaswani, Noam Shazeer, Niki Parmar...\n"
        "Google Brain, Google Research\n"
        "Abstract: The dominant sequence transduction models are based on complex recurrent or convolutional neural networks.\n"
        "We propose the Transformer, a model architecture relying entirely on an attention mechanism for machine learning."
    )
    doc2 = recognize_document("1706.03762.pdf", text=text)
    assert doc2.topic == "Machine_Learning_Transformers", f"Got {doc2.topic}"
    assert "Machine_Learning_Transformers" in doc2.context_path


def test_organic_chemistry_subject():
    doc1 = recognize_document("Organic_Chemistry_Reaction_Mechanisms.pdf")
    assert doc1.topic == "Organic_Chemistry", f"Got {doc1.topic}"
    assert doc1.context_path == ["Organic_Chemistry", "Reaction_Mechanisms"]

    # From content
    text = (
        "Principles of Organic Chemistry\n"
        "Chapter 5: Hydrocarbons, Alkanes, and Alkynes\n"
        "Electrophilic addition reaction mechanisms."
    )
    doc2 = recognize_document("chemistry_ch5.pdf", text=text)
    assert doc2.topic == "Organic_Chemistry"
    assert "Organic_Chemistry" in doc2.context_path


def test_open_domain_metadata_extraction():
    text = (
        "Project: Autonomous_Drone_Fleet\n"
        "Client: Logistics Corp\n"
        "Architecture Overview: Distributed mesh telemetry network."
    )
    ctx = extract_contextual_topic("spec.docx", text=text)
    assert ctx.topic == "Autonomous_Drone_Fleet"
    assert ctx.confidence >= 0.85


def test_rule_engine_dynamic_classification():
    tax = {
        "categories": [
            {
                "name": "Learning & Reference",
                "subcategories": [
                    {"name": "Books & Ebooks", "keywords": ["book", "algorithms"], "extensions": [".pdf"]}
                ]
            }
        ]
    }
    engine = RuleEngine(tax)

    # NASA document must classify as NASA, not fall back to Books & Ebooks
    f_nasa = FileInfo(
        id="1", path="C:/x/NASA_JWST_Optical_Design.pdf", root="C:/x", rel_dir="",
        name="NASA_JWST_Optical_Design.pdf", ext=".pdf", size=1000, mtime=0, kind="Document",
        text="", text_chars=0
    )
    v_nasa = engine.classify(f_nasa)
    assert v_nasa.category == "NASA", f"Expected category NASA, got {v_nasa.category}"
    assert v_nasa.subcategory == "James_Webb_Space_Telescope"
    assert v_nasa.method == "rules_dynamic"

    # Cinri Health API
    f_cinri = FileInfo(
        id="2", path="C:/x/Cinri_Health_API_Specification.docx", root="C:/x", rel_dir="",
        name="Cinri_Health_API_Specification.docx", ext=".docx", size=1000, mtime=0, kind="Document",
        text="", text_chars=0
    )
    v_cinri = engine.classify(f_cinri)
    assert v_cinri.category == "Cinri_Health_API"


def test_build_plan_dynamic_folder_hierarchy():
    cfg = Config()
    cfg.vault = Path("C:/Organized_Vault")
    cfg.people = ["Father", "Kush"]
    cfg.person_first_layout = True
    cfg.dynamic_context_folders = True
    tax = load_taxonomy(cfg.taxonomy_path)

    files = [
        # 1. NASA file -> C:/Organized_Vault/NASA/James_Webb_Space_Telescope/NASA_JWST_Optical_Design.pdf
        FileInfo(
            id="nasa_1", path="C:/Downloads/NASA_JWST_Optical_Design.pdf", root="C:/Downloads", rel_dir="",
            name="NASA_JWST_Optical_Design.pdf", ext=".pdf", size=50000, mtime=0, kind="Document",
            text="NASA Goddard Space Flight Center James Webb Space Telescope Optical Design", text_chars=70
        ),
        # 2. Cinri Health API -> C:/Organized_Vault/Cinri_Health_API/Cinri_Health_API_Specification.docx
        FileInfo(
            id="cinri_1", path="C:/Downloads/Cinri_Health_API_Specification.docx", root="C:/Downloads", rel_dir="",
            name="Cinri_Health_API_Specification.docx", ext=".docx", size=40000, mtime=0, kind="Document",
            text="Cinri Health API Specification Patient Endpoints", text_chars=50
        ),
        # 3. Father Office Work -> C:/Organized_Vault/Father/Office_Work/Vendor_Invoices_Q3/Father_Office_Work_Vendor_Invoices_Q3.xlsx
        FileInfo(
            id="father_1", path="C:/Downloads/Father_Office_Work_Vendor_Invoices_Q3.xlsx", root="C:/Downloads", rel_dir="",
            name="Father_Office_Work_Vendor_Invoices_Q3.xlsx", ext=".xlsx", size=30000, mtime=0, kind="Document",
            text="Office Work Vendor Invoices Q3 2024", text_chars=40
        ),
        # 4. Machine Learning Transformers -> C:/Organized_Vault/Machine_Learning_Transformers/Attention_Is_All_You_Need.pdf
        FileInfo(
            id="ml_1", path="C:/Downloads/Attention_Is_All_You_Need.pdf", root="C:/Downloads", rel_dir="",
            name="Attention_Is_All_You_Need.pdf", ext=".pdf", size=60000, mtime=0, kind="Document",
            text="Attention Is All You Need Transformer Model Machine Learning", text_chars=60
        ),
        # 5. Organic Chemistry -> C:/Organized_Vault/Organic_Chemistry/Reaction_Mechanisms/Organic_Chemistry_Reaction_Mechanisms.pdf
        FileInfo(
            id="chem_1", path="C:/Downloads/Organic_Chemistry_Reaction_Mechanisms.pdf", root="C:/Downloads", rel_dir="",
            name="Organic_Chemistry_Reaction_Mechanisms.pdf", ext=".pdf", size=70000, mtime=0, kind="Document",
            text="Organic Chemistry Reaction Mechanisms", text_chars=40
        ),
    ]

    items, stats = build_plan(cfg, files, tax, use_llm=False)
    dest_map = {Path(i.source).name: Path(i.destination) for i in items}

    # Verify 1: NASA JWST - must NOT have bogus person folder (e.g. 'Optical')
    dest_nasa = dest_map["NASA_JWST_Optical_Design.pdf"]
    rel_nasa = dest_nasa.relative_to(cfg.vault)
    assert rel_nasa == Path("Common/NASA/James_Webb_Space_Telescope/NASA_JWST_Optical_Design.pdf"), f"Unexpected NASA destination: {rel_nasa}"

    # Verify 2: Cinri Health API - must NOT have bogus person folder (e.g. 'Api')
    dest_cinri = dest_map["Cinri_Health_API_Specification.docx"]
    rel_cinri = dest_cinri.relative_to(cfg.vault)
    assert rel_cinri == Path("Common/Cinri_Health_API/Endpoints/Cinri_Health_API_Specification.docx"), f"Unexpected Cinri destination: {rel_cinri}"

    # Verify 3: Father/Office_Work/Vendor_Invoices_Q3
    dest_father = dest_map["Father_Office_Work_Vendor_Invoices_Q3.xlsx"]
    rel_father = dest_father.relative_to(cfg.vault)
    assert rel_father == Path("Father/Office_Work/Vendor_Invoices_Q3/Father_Office_Work_Vendor_Invoices_Q3.xlsx"), f"Unexpected Father destination: {rel_father}"

    # Verify 4: Machine Learning Transformers - must NOT have bogus person folder (e.g. 'Attention')
    dest_ml = dest_map["Attention_Is_All_You_Need.pdf"]
    rel_ml = dest_ml.relative_to(cfg.vault)
    assert rel_ml == Path("Common/Machine_Learning_Transformers/Attention/Attention_Is_All_You_Need.pdf"), f"Unexpected ML destination: {rel_ml}"

    # Verify 5: Organic Chemistry - must NOT have bogus person folder (e.g. 'Organic')
    dest_chem = dest_map["Organic_Chemistry_Reaction_Mechanisms.pdf"]
    rel_chem = dest_chem.relative_to(cfg.vault)
    assert rel_chem == Path("Common/Organic_Chemistry/Reaction_Mechanisms/Organic_Chemistry_Reaction_Mechanisms.pdf"), f"Unexpected Chem destination: {rel_chem}"


def test_unconstrained_space_missions():
    # 1. Novel NASA mission not in static taxonomy
    doc1 = recognize_document("NASA_Nancy_Grace_Roman_Space_Telescope_Survey.pdf", text="Infrared survey telescope")
    assert doc1.topic == "NASA"
    assert doc1.subtopic == "Nancy_Grace_Roman_Space_Telescope"
    assert doc1.context_path == ["NASA", "Nancy_Grace_Roman_Space_Telescope"]

    # 2. Europa Clipper trajectory
    doc2 = recognize_document("NASA_Europa_Clipper_Trajectory_Simulation.pdf", text="Jupiter moon Europa flyby trajectory")
    assert doc2.topic == "NASA"
    assert doc2.subtopic == "Europa_Clipper"

    # 3. ESA Rosetta comet mission
    doc3 = recognize_document("ESA_Rosetta_Comet_67P_Mission_Overview.pdf", text="European Space Agency Rosetta lander Philae")
    assert doc3.topic == "ESA"
    assert doc3.subtopic == "Rosetta"

    # 4. ISRO Chandrayaan-3 lunar lander
    doc4 = recognize_document("ISRO_Chandrayaan_3_Landing_Telemetry.pdf", text="Indian Space Research Organisation lunar lander Vikram")
    assert doc4.topic == "ISRO"
    assert doc4.subtopic == "Chandrayaan_3"

    # 5. SpaceX Starship
    doc5 = recognize_document("SpaceX_Starship_Orbital_Flight_Test_Report.pdf", text="Starship orbital test flight telemetry")
    assert doc5.topic == "SpaceX"
    assert doc5.subtopic == "Starship"


def test_dynamic_office_work_hierarchies():
    # 1. Employee Payroll Q4 must NOT be forced into Vendor_Invoices_Q4
    doc1 = recognize_document("Father_Office_Work_Employee_Payroll_Q4.xlsx", text="Payroll records for staff", people=["Father"])
    assert doc1.person == "Father"
    assert doc1.topic == "Office_Work"
    assert doc1.subtopic == "Employee_Payroll_Q4", f"Expected Employee_Payroll_Q4, got {doc1.subtopic}"
    assert doc1.context_path == ["Office_Work", "Employee_Payroll_Q4"]

    # 2. Board Meeting Minutes must NOT be forced into General
    doc2 = recognize_document("Father_Office_Work_Board_Meeting_Minutes.docx", text="Annual board minutes", people=["Father"])
    assert doc2.person == "Father"
    assert doc2.topic == "Office_Work"
    assert doc2.subtopic == "Board_Meeting_Minutes", f"Expected Board_Meeting_Minutes, got {doc2.subtopic}"

    # 3. Client Proposals
    doc3 = recognize_document("Office_Work_Client_Proposals.pdf", text="Client RFP proposal submission")
    assert doc3.topic == "Office_Work"
    assert doc3.subtopic == "Client_Proposals"


def test_explicit_marker_prefixes_and_systems():
    # Project prefix
    doc_proj = recognize_document("Project_Stripe_Checkout_Integration_Guide.pdf", text="Web checkout integration")
    assert doc_proj.topic == "Stripe_Checkout"
    assert doc_proj.subtopic == "Integration_Guide"

    # Subject prefix
    doc_subj = recognize_document("Subject_Immunology_Cellular_Defenses.docx", text="T cells and immune response")
    assert doc_subj.topic == "Immunology"
    assert doc_subj.subtopic == "Cellular_Defenses"

    # Company prefix
    doc_comp = recognize_document("Company_Acme_Robotics_Annual_Investor_Presentation.pptx", text="Acme Robotics fiscal presentation")
    assert doc_comp.topic == "Acme_Robotics"
    assert doc_comp.subtopic == "Annual_Investor_Presentation"

    # Domain prefix
    doc_dom = recognize_document("Domain_Bioinformatics_Genomic_Sequencing.pdf", text="DNA sequencing pipeline")
    assert doc_dom.topic == "Bioinformatics"
    assert doc_dom.subtopic == "Genomic_Sequencing"

    # System/Project keyword
    doc_sys = recognize_document("Tesla_Autopilot_Full_Self_Driving_Architecture.pdf", text="Autonomous neural networks")
    assert doc_sys.topic == "Tesla_Autopilot"
    assert doc_sys.subtopic == "Full_Self_Driving_Architecture"


def test_unsupervised_academic_disciplines():
    doc_qc = recognize_document("Quantum_Computing_Qubit_Coherence_Analysis.pdf", text="Qubit decoherence and error correction")
    assert doc_qc.topic == "Quantum_Computing"
    assert doc_qc.subtopic == "Qubit_Coherence"

    doc_neuro = recognize_document("Neuroscience_Synaptic_Plasticity_Study.pdf", text="Synaptic plasticity in hippocampus")
    assert doc_neuro.topic == "Neuroscience"
    assert doc_neuro.subtopic == "Synaptic_Plasticity"


def test_rule_engine_does_not_override_dynamic_topics_with_static_categories():
    cfg = Config()
    tax = load_taxonomy(cfg.taxonomy_path)
    engine = RuleEngine(tax)

    # File with 'invoice' in filename must NOT be forced into static 'Money & Paperwork / Invoices & Receipts'
    f_inv = FileInfo(
        id="f_inv", path="C:/x/Father_Office_Work_Vendor_Invoices_Q3.xlsx", root="C:/x", rel_dir="",
        name="Father_Office_Work_Vendor_Invoices_Q3.xlsx", ext=".xlsx", size=1000, mtime=0, kind="Document",
        text="Office Work Vendor Invoices Q3 2024", text_chars=40
    )
    v_inv = engine.classify(f_inv)
    assert v_inv.category == "Office_Work", f"Expected Office_Work, got {v_inv.category}"
    assert v_inv.subcategory == "Vendor_Invoices_Q3", f"Expected Vendor_Invoices_Q3, got {v_inv.subcategory}"
    assert v_inv.method == "rules_dynamic"


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
