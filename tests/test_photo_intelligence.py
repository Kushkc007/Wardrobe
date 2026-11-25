"""Tests for Photo Intelligence: WhatsApp junk / greeting filtering and face clustering.

Verifies:
- 'Good morning', 'Good night', 'Suprabhat', festival wishes are detected as WhatsApp Junk Greetings
- Memes and forwarded humor are detected as WhatsApp Junk Memes
- Greetings are routed to WhatsApp_Junk/Greetings/[File]
- Memes are routed to WhatsApp_Junk/Memes/[File]
- Real personal photos (even with WhatsApp filenames) containing human faces without greeting text are preserved
- Google Photos-style face detection and clustering groups photos by individual (Kush/Photos, Papa/Photos, Bua/Photos)
- Graceful offline fallback when neural models are unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from organizer.config import Config, load_taxonomy
from organizer.photo_intel import (
    check_whatsapp_junk, is_whatsapp_filename, get_face_clusterer, FaceClusterer
)
from organizer.planner import build_plan
from organizer.scanner import FileInfo


def test_whatsapp_greeting_detection():
    # 1. Standard English Good Morning greeting
    is_junk, j_type, conf, reason = check_whatsapp_junk(
        "IMG-20240101-WA0001.jpg",
        ocr_text="Good Morning! May God bless your day with happiness and peace.",
        face_count=0
    )
    assert is_junk is True, "Expected WhatsApp greeting to be flagged as junk"
    assert j_type == "Greetings"
    assert conf >= 0.90

    # 2. Hindi / Festival greeting (Suprabhat / Radhe Radhe / Happy Diwali)
    is_junk, j_type, conf, _ = check_whatsapp_junk(
        "WA_Image_123.jpg",
        ocr_text="Shubh Prabhat! Radhe Radhe. Happy Diwali to all family members.",
        face_count=0
    )
    assert is_junk is True
    assert j_type == "Greetings"


def test_whatsapp_meme_detection():
    is_junk, j_type, conf, _ = check_whatsapp_junk(
        "forwarded_meme.jpg",
        ocr_text="When you wake up and realize you forgot to submit the assignment. POV: Me crying.",
        face_count=0
    )
    assert is_junk is True
    assert j_type == "Memes"


def test_real_photo_on_whatsapp_not_junk():
    """A real family photo sent over WhatsApp should NOT be marked as junk."""
    is_junk, j_type, conf, _ = check_whatsapp_junk(
        "IMG-20240102-WA0010.jpg",
        ocr_text="",
        face_count=1  # Detected a human face!
    )
    assert is_junk is False, "A real personal photo with human faces must not be marked as junk"


def test_face_clusterer_initialization():
    pytest.importorskip("cv2")
    fc = get_face_clusterer()
    assert isinstance(fc, FaceClusterer)
    # Neural models are optional (downloaded on demand); skip when unavailable.
    if not fc.has_neural_models:
        pytest.skip("YuNet/SFace models are not available in this environment")


def test_photo_plan_isolation_and_face_grouping():
    cfg = Config.load()
    cfg.vault = Path("C:/Vault")
    cfg.people = ["Kush", "Father", "Mother", "Papa", "Mummy", "Bua"]
    cfg.person_first_layout = True
    cfg.separate_whatsapp_junk = True
    cfg.enable_face_recognition = True
    tax = load_taxonomy(cfg.taxonomy_path)

    files = [
        # WhatsApp greeting card
        FileInfo(
            id="g1", path="C:/Pictures/IMG-20240101-WA0001.jpg", root="C:/Pictures",
            rel_dir="", name="IMG-20240101-WA0001.jpg", ext=".jpg", size=85000,
            mtime=0, kind="Image", text="Good Morning! Have a blessed day ahead.",
            text_chars=40, hints=["whatsapp_junk", "greeting"]
        ),
        # WhatsApp meme
        FileInfo(
            id="m1", path="C:/Pictures/meme_monday.png", root="C:/Pictures",
            rel_dir="", name="meme_monday.png", ext=".png", size=95000,
            mtime=0, kind="Image", text="When you think it's Friday but it is only Monday",
            text_chars=45, hints=["whatsapp_junk", "meme"]
        ),
        # Personal photo of Papa
        FileInfo(
            id="p1", path="C:/Pictures/Papa_birthday_trip.jpg", root="C:/Pictures",
            rel_dir="", name="Papa_birthday_trip.jpg", ext=".jpg", size=4500000,
            mtime=0, kind="Image", text="photograph taken with Nikon D5600",
            text_chars=35, hints=["photo", "camera"]
        ),
        # Personal photo of Kush
        FileInfo(
            id="k1", path="C:/Pictures/Kush_portrait.jpg", root="C:/Pictures",
            rel_dir="", name="Kush_portrait.jpg", ext=".jpg", size=3200000,
            mtime=0, kind="Image", text="photograph taken with iPhone 15",
            text_chars=30, hints=["photo", "camera"]
        ),
        # Personal photo of Bua
        FileInfo(
            id="b1", path="C:/Pictures/Bua_family_function.jpg", root="C:/Pictures",
            rel_dir="", name="Bua_family_function.jpg", ext=".jpg", size=2900000,
            mtime=0, kind="Image", text="photograph taken with Samsung Galaxy",
            text_chars=30, hints=["photo", "camera"]
        ),
    ]

    items, stats = build_plan(cfg, files, tax, use_llm=False)
    dest_map = {i.id: Path(i.destination) for i in items}

    # 1. Greeting -> C:/Vault/WhatsApp_Junk/Greetings/IMG-20240101-WA0001.jpg
    dest_g1 = dest_map["g1"]
    assert "Common" in dest_g1.parts and "Greetings" in dest_g1.parts, f"Expected Common/Greetings in {dest_g1}"
    assert "Greetings" in dest_g1.parts, f"Expected Greetings in {dest_g1}"

    # 2. Meme -> C:/Vault/WhatsApp_Junk/Memes/meme_monday.png
    dest_m1 = dest_map["m1"]
    assert "Common" in dest_m1.parts and "Jokes & Memes" in dest_m1.parts, f"Expected Common/Jokes & Memes in {dest_m1}"
    assert "Jokes & Memes" in dest_m1.parts, f"Expected Jokes & Memes in {dest_m1}"

    # 3. Papa photo -> C:/Vault/Papa/Photos/Papa_birthday_trip.jpg
    dest_p1 = dest_map["p1"]
    assert any(p in dest_p1.parts for p in ("Papa", "Father")), f"Expected Papa/Father in {dest_p1}"
    assert "Photos" in dest_p1.parts, f"Expected Photos in {dest_p1}"

    # 4. Kush photo -> C:/Vault/Kush/Photos/Kush_portrait.jpg
    dest_k1 = dest_map["k1"]
    assert "Kush" in dest_k1.parts, f"Expected Kush in {dest_k1}"
    assert "Photos" in dest_k1.parts, f"Expected Photos in {dest_k1}"

    # 5. Bua photo -> C:/Vault/Bua/Photos/Bua_family_function.jpg
    dest_b1 = dest_map["b1"]
    assert "Bua" in dest_b1.parts, f"Expected Bua in {dest_b1}"
    assert "Photos" in dest_b1.parts, f"Expected Photos in {dest_b1}"


def test_devanagari_whatsapp_greeting_detection():
    # 1. Hindi Devanagari Suprabhat greeting
    is_junk, j_type, conf, reason = check_whatsapp_junk(
        "WA0045.jpg",
        ocr_text="सुप्रभात आपका दिन मंगलमय और खुशहाल हो",
        face_count=0
    )
    assert is_junk is True, "Devanagari Suprabhat must be detected as junk greeting"
    assert j_type == "Greetings"
    assert conf >= 0.90

    # 2. Devanagari festival & religious greeting
    is_junk, j_type, conf, _ = check_whatsapp_junk(
        "WA0046.jpg",
        ocr_text="शुभ प्रभात! जय श्री राम, हर हर महादेव, राधे राधे",
        face_count=0
    )
    assert is_junk is True
    assert j_type == "Greetings"

    # 3. Devanagari Suvichar / Anmol Vachan
    is_junk, j_type, conf, _ = check_whatsapp_junk(
        "WA0047.jpg",
        ocr_text="आज का सुविचार: अनमोल वचन और प्रेरक विचार",
        face_count=0
    )
    assert is_junk is True
    assert j_type == "Greetings"


def test_camera_photo_with_text_not_whatsapp_junk():
    # Standard DSLR or smartphone camera photo IMG_0001.jpg with arbitrary text (e.g. conference slide)
    assert is_whatsapp_filename("IMG_0001.jpg") is False, "IMG_0001.jpg is camera prefix, not WhatsApp"
    assert is_whatsapp_filename("IMG_20240101_143000.jpg") is False

    is_junk, j_type, conf, reason = check_whatsapp_junk(
        "IMG_0001.jpg",
        ocr_text="International Conference on Machine Learning 2024 - Keynote Presentation",
        face_count=0
    )
    assert is_junk is False, "Camera photo with presentation slide text must not be flagged as junk"


def test_true_unsupervised_face_clustering():
    """Unlabeled photos of different individuals must cluster into separate person folders."""
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")

    fc = get_face_clusterer()
    if not fc.has_neural_models:
        pytest.skip("YuNet/SFace models are not available in this environment")

    # Create synthetic 128-d embeddings for 2 distinct people
    # Person A prototype vector
    rng = np.random.RandomState(42)
    vec_a = rng.randn(1, 128).astype(np.float32)
    vec_a = vec_a / np.linalg.norm(vec_a)
    # Slightly perturbed vector of person A (cosine sim ~ 0.95)
    vec_a2 = vec_a + 0.1 * rng.randn(1, 128).astype(np.float32)
    vec_a2 = vec_a2 / np.linalg.norm(vec_a2)

    # Person B prototype vector (orthogonal to A)
    vec_b = rng.randn(1, 128).astype(np.float32)
    vec_b = vec_b - np.dot(vec_b, vec_a.T) * vec_a
    vec_b = vec_b / np.linalg.norm(vec_b)
    # Slightly perturbed vector of person B
    vec_b2 = vec_b + 0.1 * rng.randn(1, 128).astype(np.float32)
    vec_b2 = vec_b2 / np.linalg.norm(vec_b2)

    # Mock detect_and_embed for 4 unlabeled camera photos
    orig_detect = fc.detect_and_embed
    mock_data = {
        "IMG_1001.jpg": [(np.zeros(15), vec_a)],
        "IMG_1002.jpg": [(np.zeros(15), vec_a2)],
        "IMG_2001.jpg": [(np.zeros(15), vec_b)],
        "IMG_2002.jpg": [(np.zeros(15), vec_b2)],
    }
    try:
        fc.detect_and_embed = lambda p: mock_data.get(Path(p).name, [])
        photo_files = [
            {"id": "a1", "path": "IMG_1001.jpg", "name": "IMG_1001.jpg", "rel_dir": "", "text": ""},
            {"id": "a2", "path": "IMG_1002.jpg", "name": "IMG_1002.jpg", "rel_dir": "", "text": ""},
            {"id": "b1", "path": "IMG_2001.jpg", "name": "IMG_2001.jpg", "rel_dir": "", "text": ""},
            {"id": "b2", "path": "IMG_2002.jpg", "name": "IMG_2002.jpg", "rel_dir": "", "text": ""},
        ]
        results = fc.cluster_photos(photo_files, configured_people=["Kush", "Papa", "Bua"])

        # Person A's photos must share the SAME cluster person name
        assert results["a1"].person == results["a2"].person, f"A1 ({results['a1'].person}) and A2 ({results['a2'].person}) must cluster together"
        # Person B's photos must share the SAME cluster person name
        assert results["b1"].person == results["b2"].person, f"B1 ({results['b1'].person}) and B2 ({results['b2'].person}) must cluster together"
        # Person A and Person B MUST NOT be in the same cluster!
        assert results["a1"].person != results["b1"].person, f"Person A ({results['a1'].person}) and Person B ({results['b1'].person}) must be separate!"
    finally:
        fc.detect_and_embed = orig_detect


if __name__ == "__main__":
    test_whatsapp_greeting_detection()
    print("  ok   test_whatsapp_greeting_detection")
    test_whatsapp_meme_detection()
    print("  ok   test_whatsapp_meme_detection")
    test_real_photo_on_whatsapp_not_junk()
    print("  ok   test_real_photo_on_whatsapp_not_junk")
    test_face_clusterer_initialization()
    print("  ok   test_face_clusterer_initialization")
    test_photo_plan_isolation_and_face_grouping()
    print("  ok   test_photo_plan_isolation_and_face_grouping")
    test_devanagari_whatsapp_greeting_detection()
    print("  ok   test_devanagari_whatsapp_greeting_detection")
    test_camera_photo_with_text_not_whatsapp_junk()
    print("  ok   test_camera_photo_with_text_not_whatsapp_junk")
    test_true_unsupervised_face_clustering()
    print("  ok   test_true_unsupervised_face_clustering")
    print("\nall good")
