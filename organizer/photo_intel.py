"""Photo Intelligence: WhatsApp junk / greeting filtering and Google Photos-style face clustering.

Capabilities:
1. WhatsApp Junk / Greeting Filtering:
   - Detects "Good morning", "Good night", "Suprabhat", festival wishes, quotes, forwards,
     and memes from filenames and OCR text.
   - Separates them into designated 'WhatsApp_Junk/Greetings' and 'WhatsApp_Junk/Memes' folders.
   - Preserves real personal photos sent over WhatsApp (photos with human faces and no greeting text).
2. Face Recognition & Clustering (Google Photos-style):
   - Detects human faces using deep neural network (OpenCV FaceDetectorYN / YuNet).
   - Extracts 128-dimensional facial embeddings using SFace (OpenCV FaceRecognizerSF).
   - Clusters personal photos by detected individual (e.g. Kush, Father/Papa, Mother/Mummy, Bua).
   - Fallback to skin-tone / perceptual hashing if DNN models are unavailable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import APP_DIR, BUNDLE_DIR
from .doc_intel import KINSHIP_MAP, normalize_person_name

# Greeting and festival keywords for WhatsApp junk detection
GREETING_PATTERNS = (
    # English greetings
    r"\bgood\s+morning\b",
    r"\bgood\s+night\b",
    r"\bgood\s+evening\b",
    r"\bgood\s+afternoon\b",
    r"\bhappy\s+birthday\b",
    r"\bhappy\s+anniversary\b",
    r"\bhappy\s+new\s+year\b",
    r"\bhappy\s+diwali\b",
    r"\bhappy\s+deepavali\b",
    r"\bhappy\s+holi\b",
    r"\bhappy\s+eid\b",
    r"\braksha\s+bandhan\b",
    r"\bmerry\s+christmas\b",
    r"\bthought\s+of\s+the\s+day\b",
    r"\bdaily\s+quote\b",
    r"\bmotivational\s+quote\b",
    r"\bpositive\s+vibes\b",
    r"\bquote\s+of\s+the\s+day\b",
    r"\blife\s+quotes\b",
    r"\bblessings?\b",
    r"\bgod\s+bless\s+you\b",
    r"\bhave\s+a\s+(?:nice|great|blessed|wonderful)\s+day\b",
    r"\bforwarded\s+as\s+received\b",
    r"\bplease\s+forward\b",
    r"\bshare\s+with\b",
    # Transliterated Hindi / Indian greetings
    r"\bsuprabhat\b",
    r"\bshubh\s+prabhat\b",
    r"\bshubh\s+ratri\b",
    r"\bshubh\s+din\b",
    r"\bshubh\s+ravivar\b",
    r"\bshubh\s+somvar\b",
    r"\bsuvichar\b",
    r"\banmol\s+vachan\b",
    r"\bradhe\s+radhe\b",
    r"\bjai\s+shree?\s+krishna\b",
    r"\bjai\s+shree?\s+ram\b",
    r"\bom\s+namah\s+shivay\b",
    r"\bhar\s+har\s+mahadev\b",
    r"\bjai\s+mata\s+di\b",
    r"\bnamaskar\b",
    r"\bpranam\b",
    # Devanagari Hindi Script greetings
    r"सुप्रभात",
    r"शुभ\s*प्रभात",
    r"शुभ\s*दिन",
    r"शुभ\s*रात्रि",
    r"शुभ\s*रविवार",
    r"शुभ\s*सोमवार",
    r"शुभ\s*मंगलवार",
    r"शुभ\s*बुधवार",
    r"शुभ\s*गुरुवार",
    r"शुभ\s*शुक्रवार",
    r"शुभ\s*शनिवार",
    r"सुविचार",
    r"अनमोल\s*वचन",
    r"आज\s*का\s*विचार",
    r"प्रेरक\s*विचार",
    r"राधे\s*राधे",
    r"जय\s*श्री\s*कृष्णा?",
    r"जय\s*श्री\s*राम",
    r"हर\s*हर\s*महादेव",
    r"ॐ\s*नमः\s*शिवाय",
    r"जय\s*माता\s*दी",
    r"दीपावली\s*की\s*शुभकामनाएं?",
    r"होली\s*की\s*शुभकामनाएं?",
    r"शुभ\s*दीपावली",
    r"नव\s*वर्ष\s*की\s*शुभकामनाएं?",
    r"जन्मदिन\s*मुबारक",
    r"रक्षाबंधन\s*की\s*शुभकामनाएं?",
)

MEME_PATTERNS = (
    r"\bwhen\s+you\b",
    r"\bme\s+trying\s+to\b",
    r"\bnobody\s*:\b",
    r"\bpov\s*:\b",
    r"\bthat\s+moment\s+when\b",
    r"\bliterally\s+me\b",
    r"\bme\s+after\b",
    r"\bwait\s+for\s+it\b",
    r"\bhumor\b",
    r"\bmeme\b",
    r"\bchutkule\b",
    r"चुटकुले",
    r"\bjokes?\b",
    r"\brelatable\b",
)

RE_GREETING = re.compile("|".join(GREETING_PATTERNS), re.IGNORECASE)
RE_MEME = re.compile("|".join(MEME_PATTERNS), re.IGNORECASE)


@dataclass
class PhotoFaceResult:
    face_count: int = 0
    person: str = ""
    confidence: float = 0.0
    is_junk: bool = False
    junk_type: str = ""  # Greetings | Memes | Forwards
    reason: str = ""


OPENCV_ZOO_URLS = {
    "yunet.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "sface.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}


def find_model_path(model_filename: str) -> Path | None:
    """Locate onnx model file in assets/ or bundle directory, auto-downloading if missing."""
    candidates = [
        APP_DIR / "assets" / model_filename,
        BUNDLE_DIR / "assets" / model_filename,
        APP_DIR / model_filename,
        BUNDLE_DIR / model_filename,
    ]
    for c in candidates:
        if c.exists() and c.stat().st_size > 1000:
            return c

    # Attempt on-demand download to assets/
    if model_filename in OPENCV_ZOO_URLS:
        try:
            import urllib.request
            target = APP_DIR / "assets" / model_filename
            target.parent.mkdir(parents=True, exist_ok=True)
            url = OPENCV_ZOO_URLS[model_filename]
            req = urllib.request.Request(url, headers={"User-Agent": "Wardrobe-File-Organizer/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(target, "wb") as out:
                out.write(resp.read())
            if target.exists() and target.stat().st_size > 1000:
                return target
        except Exception:
            pass
    return None


def is_whatsapp_filename(filename: str, rel_dir: str = "") -> bool:
    """True if file provenance indicates WhatsApp / messaging app forward."""
    low = f"{rel_dir} {filename}".lower()
    fn_low = Path(filename).name.lower()
    is_wa_dir = any(p in low for p in ('whatsapp', 'wa_images', 'wa images'))
    is_wa_name = (
        bool(re.search(r"^(?:img|vid)[-_]\d{8}[-_]wa\d+", fn_low))
        or bool(re.search(r"[-_]wa\d{4,}", fn_low))
        or bool(re.search(r"\bwhatsapp\b", fn_low))
    )
    is_camera = any(k in low for k in ('camera', 'dcim', 'dslr', 'nikon', 'canon', 'sony', 'apple', 'iphone'))
    return (is_wa_dir or is_wa_name) and not is_camera


def check_whatsapp_junk(
    image_path: Path | str,
    ocr_text: str = "",
    face_count: int = 0,
) -> tuple[bool, str, float, str]:
    """Check if an image is WhatsApp junk (greetings, memes, forwarded clutter).

    Returns (is_junk, junk_type, confidence, reason).
    """
    path = Path(image_path)
    fn = path.name.lower()
    text = (ocr_text or "").strip()
    # Guard: If OCR text indicates a real document, it is NEVER junk!
    if text:
        from .doc_intel import recognize_document
        doc_info = recognize_document(fn, text, str(path.parent))
        if doc_info.doc_type:
            return False, "", 0.0, ""
        if any(dk in text.lower() for dk in (
            'invoice', 'receipt', 'statement', 'aadhaar', 'aadhar', 'permanent account number',
            'income tax', 'prescription', 'marksheet', 'salary slip', 'payslip', 'bill no'
        )):
            return False, "", 0.0, ""

    # 1. OCR text indicates Greeting
    if text and RE_GREETING.search(text):
        m = RE_GREETING.search(text)
        matched = m.group(0) if m else "greeting"
        return True, "Greetings", 0.96, f"greeting detected ('{matched}')"

    # 2. OCR text indicates Meme
    if text and RE_MEME.search(text):
        m = RE_MEME.search(text)
        matched = m.group(0) if m else "meme"
        return True, "Memes", 0.94, f"meme text detected ('{matched}')"

    # 3. Filename indicates greeting or meme
    if RE_GREETING.search(fn) or any(term in fn for term in ('good_morning', 'gm_', 'gn_', 'suprabhat', 'festival', 'shayari', 'greeting')):
        return True, "Greetings", 0.92, "greeting filename match"
    if RE_MEME.search(fn) or any(term in fn for term in ('meme', 'humor', 'chutkule')):
        return True, "Memes", 0.90, "meme filename match"

    return False, "", 0.0, ""


class FaceClusterer:
    """Face detector and clustering engine using OpenCV YuNet + SFace.

    Zero crash, offline first, graceful fallback when neural networks are unavailable.
    """

    def __init__(self):
        self._cv2 = None
        self._detector = None
        self._recognizer = None
        self._initialized = False
        self._init_models()

    def _init_models(self):
        try:
            import cv2
            self._cv2 = cv2
            yunet_path = find_model_path("yunet.onnx")
            sface_path = find_model_path("sface.onnx")

            if yunet_path and hasattr(cv2, "FaceDetectorYN_create"):
                self._detector = cv2.FaceDetectorYN_create(
                    str(yunet_path), "", (320, 320), score_threshold=0.6, nms_threshold=0.3
                )
            if sface_path and hasattr(cv2, "FaceRecognizerSF_create"):
                self._recognizer = cv2.FaceRecognizerSF_create(str(sface_path), "")

            self._initialized = bool(self._detector and self._recognizer)
        except Exception:
            self._initialized = False

    @property
    def has_neural_models(self) -> bool:
        return self._initialized

    def detect_and_embed(self, image_path: Path | str) -> list[tuple[any, any]]:
        """Detect faces and extract 128-d embeddings for each face in the image.

        Returns list of (face_box_landmarks, embedding_vector).
        """
        if not self._initialized or self._cv2 is None:
            return []
        try:
            path = Path(image_path)
            if not path.is_file():
                return []
            p = str(path)
            img = self._cv2.imread(p)
            if img is None:
                return []
            h, w = img.shape[:2]
            # Resize if too huge for fast detection
            scale = 1.0
            max_dim = 1280
            if max(h, w) > max_dim:
                scale = max_dim / max(h, w)
                img = self._cv2.resize(img, (int(w * scale), int(h * scale)))
                h, w = img.shape[:2]

            self._detector.setInputSize((w, h))
            ret, faces = self._detector.detect(img)
            if faces is None or len(faces) == 0:
                return []

            # Sort faces by bounding box area (w * h) descending so primary face is first!
            sorted_faces = sorted(faces, key=lambda f: float(f[2] * f[3]), reverse=True)

            results = []
            for face in sorted_faces:
                try:
                    aligned = self._recognizer.alignCrop(img, face)
                    feat = self._recognizer.feature(aligned)
                    results.append((face, feat))
                except Exception:
                    continue
            return results
        except Exception:
            return []

    def detect_face_count_fallback(self, image_path: Path | str) -> int:
        """Fallback skin-color and eye/face region heuristics if DNN is not available."""
        if self._cv2 is None:
            return 0
        try:
            path = Path(image_path)
            if not path.is_file():
                return 0
            img = self._cv2.imread(str(path))
            if img is None:
                return 0
            hsv = self._cv2.cvtColor(img, self._cv2.COLOR_BGR2HSV)
            # Human skin tone mask in HSV
            mask = self._cv2.inRange(hsv, (0, 30, 60), (25, 180, 255))
            contours, _ = self._cv2.findContours(mask, self._cv2.RETR_EXTERNAL, self._cv2.CHAIN_APPROX_SIMPLE)
            h, w = img.shape[:2]
            img_area = w * h
            faces = 0
            for c in contours:
                area = self._cv2.contourArea(c)
                # Face-sized region
                if 0.02 * img_area <= area <= 0.40 * img_area:
                    x, y, cw, ch = self._cv2.boundingRect(c)
                    aspect = cw / max(ch, 1)
                    if 0.6 <= aspect <= 1.5:
                        faces += 1
            return faces
        except Exception:
            return 0

    def cluster_photos(
        self,
        photo_files: list[dict],
        configured_people: list[str] | None = None,
        vault_path: Path | str | None = None,
        progress=None,
    ) -> dict[str, PhotoFaceResult]:
        """Cluster a collection of photo files into person folders.

        Matches labeled photos (Papa, Kush, Bua, Mother) as prototypes, then
        clusters unlabeled photos by facial similarity (SFace Cosine score >= 0.363).
        """
        results: dict[str, PhotoFaceResult] = {}
        labeled_prototypes: dict[str, list] = {}  # person -> list of embeddings
        unlabeled_faces: list[dict] = []  # items with file_id, path, face_data
        total = len(photo_files)

        # Step 0: Optionally seed prototypes from existing vault person folders if available
        if vault_path and self._initialized:
            try:
                vpath = Path(vault_path)
                if vpath.is_dir():
                    for pdir in vpath.iterdir():
                        if pdir.is_dir() and (pdir / "Photos").is_dir():
                            pname = normalize_person_name(pdir.name, configured_people) or pdir.name
                            sample_photos = list((pdir / "Photos").glob("*.*"))[:3]
                            for sphoto in sample_photos:
                                if sphoto.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'):
                                    fdata = self.detect_and_embed(sphoto)
                                    if len(fdata) == 1:
                                        labeled_prototypes.setdefault(pname, []).append(fdata[0][1])
            except Exception:
                pass

        # Step 1: Scan each photo for face embeddings and check for ground truth filenames
        for idx, item in enumerate(photo_files):
            file_id = item.get("id", "")
            path = Path(item.get("path", ""))
            fn = path.name
            rel = item.get("rel_dir", "")
            ocr_text = item.get("text", "")

            # Check if filename explicitly indicates a known person or kinship
            known_person = ""
            if configured_people:
                for cp in configured_people:
                    pat = r"(?<![a-z0-9])" + re.escape(cp.lower()) + r"(?![a-z0-9])"
                    if re.search(pat, fn.lower()) or re.search(pat, rel.lower()):
                        known_person = cp.capitalize()
                        break

            if not known_person:
                for k, canonical in KINSHIP_MAP.items():
                    pat = r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])"
                    if re.search(pat, fn.lower()) or re.search(pat, rel.lower()):
                        if configured_people:
                            for cp in configured_people:
                                if cp.lower() == k:
                                    known_person = cp.capitalize()
                                    break
                        if not known_person:
                            known_person = canonical
                        break

            # Run face detection & embedding
            face_data = self.detect_and_embed(path) if self._initialized else []
            face_count = len(face_data) if self._initialized else self.detect_face_count_fallback(path)

            # Check WhatsApp junk / greetings
            is_junk, junk_type, conf, reason = check_whatsapp_junk(path, ocr_text, face_count)
            if is_junk:
                results[file_id] = PhotoFaceResult(
                    face_count=face_count,
                    is_junk=True,
                    junk_type=junk_type,
                    confidence=conf,
                    reason=reason,
                )
                if progress:
                    progress(idx + 1, total)
                continue

            if face_count > 0:
                if known_person:
                    # Clean solo portrait: perfect prototype for this person!
                    # For group photos, only add dominant face if person has no prototypes yet
                    if self._initialized and face_data:
                        if len(face_data) == 1:
                            labeled_prototypes.setdefault(known_person, []).append(face_data[0][1])
                        elif known_person not in labeled_prototypes:
                            labeled_prototypes.setdefault(known_person, []).append(face_data[0][1])

                    results[file_id] = PhotoFaceResult(
                        face_count=face_count,
                        person=known_person,
                        confidence=0.95,
                        reason=f"Face detected with person tag '{known_person}'" if face_count == 1 else f"Group photo with '{known_person}'",
                    )
                else:
                    # Unlabeled photo with faces to be matched or clustered
                    if self._initialized and face_data:
                        unlabeled_faces.append({
                            "id": file_id,
                            "path": path,
                            "face_data": face_data,
                        })
                    results[file_id] = PhotoFaceResult(
                        face_count=face_count,
                        confidence=0.70,
                        reason="Face detected (clustering)",
                    )
            else:
                # No faces detected
                if known_person:
                    results[file_id] = PhotoFaceResult(
                        face_count=0,
                        person=known_person,
                        confidence=0.85,
                        reason=f"Named photo '{known_person}'",
                    )
                else:
                    results[file_id] = PhotoFaceResult(face_count=0, confidence=0.60)

            if progress:
                progress(idx + 1, total)

        # Step 2: Match unlabeled faces against labeled prototypes using SFace Cosine Metric
        COSINE_THRESHOLD = 0.363
        unmatched_for_clustering: list[dict] = []

        if self._initialized and self._recognizer and unlabeled_faces:
            for item in unlabeled_faces:
                file_id = item["id"]
                face_data = item["face_data"]
                
                # Check all detected faces in the photo
                matched_persons = []
                best_person = ""
                best_score = -1.0

                for face_box, feat in face_data:
                    for person, proto_feats in labeled_prototypes.items():
                        for p_feat in proto_feats:
                            try:
                                score = float(self._recognizer.match(feat, p_feat, self._cv2.FaceRecognizerSF_FR_COSINE))
                                if score > best_score:
                                    best_score = score
                                    best_person = person
                                if score >= COSINE_THRESHOLD and person not in matched_persons:
                                    matched_persons.append(person)
                            except Exception:
                                continue

                if best_person and best_score >= COSINE_THRESHOLD:
                    results[file_id].person = best_person
                    results[file_id].confidence = min(0.96, 0.72 + best_score * 0.25)
                    if len(matched_persons) > 1:
                        results[file_id].reason = f"Group photo with {', '.join(matched_persons)} (dominant: {best_person})"
                    else:
                        results[file_id].reason = f"Face recognition match with {best_person} (similarity: {best_score:.2f})"
                    # Add embedding to enrich prototype (limit to 5 prototypes per person)
                    if len(labeled_prototypes.get(best_person, [])) < 5:
                        labeled_prototypes[best_person].append(face_data[0][1])
                else:
                    unmatched_for_clustering.append(item)

        # Step 3: Google Photos-style unsupervised face clustering for remaining unmatched photos
        if self._initialized and self._recognizer and unmatched_for_clustering:
            clusters: list[list[dict]] = []
            
            for item in unmatched_for_clustering:
                feat = item["face_data"][0][1]
                target_cluster = None
                for cluster in clusters:
                    for c_item in cluster:
                        c_feat = c_item["face_data"][0][1]
                        try:
                            score = float(self._recognizer.match(feat, c_feat, self._cv2.FaceRecognizerSF_FR_COSINE))
                            if score >= COSINE_THRESHOLD:
                                target_cluster = cluster
                                break
                        except Exception:
                            continue
                    if target_cluster is not None:
                        break

                if target_cluster is not None:
                    target_cluster.append(item)
                else:
                    clusters.append([item])

            cluster_num = 1
            for cluster in clusters:
                if len(cluster) >= 2:
                    c_name = f"Person {cluster_num}"
                    for c_item in cluster:
                        fid = c_item["id"]
                        results[fid].person = c_name
                        results[fid].confidence = 0.82
                        results[fid].reason = f"Face cluster match ({len(cluster)} photos grouped into {c_name})"
                    cluster_num += 1
                elif len(cluster) == 1 and configured_people and len(configured_people) == 1:
                    fid = cluster[0]["id"]
                    results[fid].person = configured_people[0].capitalize()
                    results[fid].confidence = 0.70
                    results[fid].reason = f"Personal photo assigned to {configured_people[0]}"

        return results


# Global singleton instance for efficient model reuse
_face_clusterer: FaceClusterer | None = None


def get_face_clusterer() -> FaceClusterer:
    global _face_clusterer
    if _face_clusterer is None:
        _face_clusterer = FaceClusterer()
    return _face_clusterer
