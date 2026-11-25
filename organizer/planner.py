"""Build a move plan with intelligent entity document recognition, WhatsApp junk isolation, and Google Photos-style face clustering."""
from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from pathlib import Path

from .config import Config
from .doc_intel import (
    recognize_document, KINSHIP_MAP, PERSON_STOPWORDS, FOLDER_NAME_STOPWORDS, extract_contextual_topic, is_personal_doc_candidate,
    detect_person_from_filename_or_path
)
from .photo_intel import (
    get_face_clusterer, PhotoFaceResult
)
from .family import load_profile, route_file as family_route, route_to_destination
from .llm import classify as llm_classify
from .rules import (
    RuleEngine, Verdict, IMAGE_EXTENSIONS
)
from .scanner import FileInfo
from .audit import hash_file

RESERVED = set('<>:"/\\|?*')

COMMON_STOPWORDS = PERSON_STOPWORDS
KINSHIP = set(KINSHIP_MAP.keys())

DOC_TYPE_TO_CATEGORY = {
    "Resume": "Work & Clients",
    "Biometrics": "Personal & Life",
    "Education": "Learning & Reference",
    "Health": "Personal & Life",
    "Salary": "Money & Paperwork",
    "Taxes": "Money & Paperwork",
    "Banking": "Money & Paperwork",
    "Legal": "Work & Clients",
}


@dataclass
class PlanItem:
    id: str
    source: str
    destination: str
    category: str
    subcategory: str
    confidence: float
    reason: str
    method: str
    size: int
    mtime: float
    status: str = "ready"  # ready | low_confidence | conflict | protected
    is_dir: bool = False
    person: str = ""
    topic: str = ""
    context_path: list[str] = field(default_factory=list)
    duplicate_of: str = ""


def safe_name(name: str) -> str:
    cleaned = "".join("_" if c in RESERVED else c for c in name).strip(" .")
    return cleaned or "unnamed"


# Words that look like names in a filename but are document/section words.
# This only guards person detection; it is not a folder taxonomy.
NON_NAME_WORDS = {
    "office", "rent", "agreement", "bank", "statement", "form", "salary",
    "tax", "property", "school", "college", "hospital", "insurance", "policy",
    "aadhaar", "aadhar", "pan", "passport", "license", "licence", "invoice",
    "receipt", "report", "project", "notes", "book", "certificate", "degree",
    "marksheet", "prescription", "medical", "resume", "cv", "biodata", "photo",
    "image", "video", "document", "documents", "scan", "copy", "final",
    "download", "downloads", "whatsapp", "screenshot", "statement", "bill",
    "voucher", "cheque", "loan", "credit", "debit", "account", "id", "card",
}

def detect_person(f: FileInfo, people: list[str] | None = None) -> str:
    """Zero-config auto-detection of family members / people from filenames, folders, text and images."""
    name_low = f.name.lower()
    rel_low = f.rel_dir.lower()

    # 1. Check user-configured people list if provided
    if people:
        for p in people:
            p_clean = p.strip()
            if not p_clean:
                continue
            pat = r"(?<![a-z0-9])" + re.escape(p_clean.lower()) + r"(?![a-z0-9])"
            if re.search(pat, name_low) or re.search(pat, rel_low):
                return p_clean.capitalize()

    # 2. Kinship names (Papa, Mummy, Dad, Mom, Bhai, Didi, Bua, etc.)
    for k, canonical in KINSHIP_MAP.items():
        pat = r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])"
        if re.search(pat, name_low) or re.search(pat, rel_low):
            if people:
                for cp in people:
                    if cp.lower() == k:
                        return cp.capitalize()
            return canonical

    is_personal = is_personal_doc_candidate(f.name, f.rel_dir, getattr(f, "text", ""))

    # 3. Dynamic Folder Provenance: e.g. 'Downloads/Kush/file.pdf'
    if is_personal:
        parts = re.split(r"[\\/]", f.rel_dir)
        for part in reversed(parts):
            cleaned = re.sub(r"[^a-zA-Z]", "", part).strip()
            if cleaned.lower() not in COMMON_STOPWORDS and 2 <= len(cleaned) <= 20:
                if cleaned.lower() not in FOLDER_NAME_STOPWORDS:
                    return cleaned.capitalize()

    # 4. Proper noun extraction from filename ONLY for personal documents (e.g. 'Passport Alex', 'Sam Resume')
    if is_personal:
        stem = Path(f.name).stem
        tokens = re.split(r"[^a-zA-Z0-9]+", stem)
        candidates = []
        for t in tokens:
            if not t or any(c.isdigit() for c in t):
                continue
            if not re.match(r"^[a-zA-Z]+$", t):
                continue
            t_low = t.lower()
            if (t_low in COMMON_STOPWORDS or t_low in NON_NAME_WORDS
                    or len(t) < 3 or len(t) > 20):
                continue
            candidates.append(t.capitalize())

        if candidates:
            return candidates[0]

    # 5. Extract from document intelligence if text is available
    if getattr(f, "text", ""):
        doc_info = recognize_document(f.name, f.text, f.rel_dir, people)
        if doc_info.person:
            return doc_info.person

    return ""


def build_plan(
    cfg: Config,
    files: list[FileInfo],
    taxonomy: dict,
    use_llm: bool = True,
    progress=None,
) -> tuple[list[PlanItem], dict]:
    """Return (plan items, stats) with deep document intelligence, WhatsApp junk filtering, and face clustering."""
    engine = RuleEngine(taxonomy, cfg.fallback)
    verdicts: dict[str, Verdict] = {}
    llm_error = ""
    llm_used = 0

    if use_llm and cfg.llm.usable:
        result = llm_classify(cfg, taxonomy, files)
        verdicts.update(result.verdicts)
        llm_used = len(result.verdicts)
        llm_error = result.error

    # Pre-cluster photos if face recognition or WhatsApp junk separation is enabled
    photo_results: dict[str, PhotoFaceResult] = {}
    is_photo_map: dict[str, bool] = {}
    if getattr(cfg, "enable_face_recognition", True) or getattr(cfg, "separate_whatsapp_junk", True):
        photo_files = []
        for f in files:
            ext = f.ext.lower()
            hints = {h.lower() for h in getattr(f, "hints", []) or []}
            is_photo = ext in IMAGE_EXTENSIONS and not ({"scan", "document"} & hints)
            is_photo_map[f.id] = is_photo
            if is_photo or ext in IMAGE_EXTENSIONS:
                photo_files.append({
                    "id": f.id,
                    "path": f.path,
                    "name": f.name,
                    "rel_dir": f.rel_dir,
                    "text": f.text,
                    "hints": list(hints),
                })
        if photo_files:
            clusterer = get_face_clusterer()
            photo_results = clusterer.cluster_photos(
                photo_files,
                configured_people=getattr(cfg, "people", []),
                vault_path=getattr(cfg, "vault", None)
            )

    items: list[PlanItem] = []
    seen_dest: dict[str, int] = {}
    family = load_profile(cfg) if getattr(cfg, "family_layout", False) else None
    if family is not None and family.people:
        cfg.people = sorted(set(getattr(cfg, "people", [])) | set(family.person_names()))

    # ---- On-the-spot folder learning ----------------------------------
    # Read every file once, then let the labels emerge from the actual scan.
    # No family, no document category and no folder tree is predefined.
    label_learner = None
    doc_infos: dict[str, object] = {}
    if family is not None and family.enabled:
        from .labels import make_learner
        label_learner = make_learner(family, cfg)
        for f in files:
            if f.is_dir:
                continue
            di = recognize_document(f.name, f.text, f.rel_dir, getattr(cfg, "people", []))
            doc_infos[f.id] = di
            label_learner.observe(f.id, f.name, f.text, f.rel_dir, di)
        label_learner.finalize()

    for idx, f in enumerate(files):
        verdict = verdicts.get(f.id)
        if verdict is None:
            verdict = engine.classify(f)

        cat = verdict.category
        sub = verdict.subcategory
        conf = verdict.confidence
        reason = verdict.reason
        method = verdict.method
        person = ""
        doc_type = ""
        is_photo = is_photo_map.get(f.id, False)
        is_junk = False

        photo_res = photo_results.get(f.id)
        ext = f.ext.lower()
        hints = {h.lower() for h in getattr(f, "hints", []) or []}
        context_path: list[str] = []
        discovered_topic = ""
        discovered_subtopic = ""
        doc_info = None
        family_dest: Path | None = None

        # ---------------------------------------------------------
        # 1. Document & Entity Recognition (Runs FIRST!)
        # Real personal documents (Resume, Biometrics, Education, Health, Salary)
        # and Dynamic Contextual Topics (NASA, Cinri Health API, Office Work, etc.)
        # ---------------------------------------------------------
        if not f.is_dir:
            doc_info = doc_infos.get(f.id) or recognize_document(f.name, f.text, f.rel_dir, getattr(cfg, "people", []))
            if doc_info.context_path:
                context_path = list(doc_info.context_path)
                discovered_topic = doc_info.topic
                discovered_subtopic = doc_info.subtopic
                cat = doc_info.topic
                sub = doc_info.subtopic or doc_info.topic
                conf = max(conf, doc_info.confidence)
                reason = doc_info.reason
                method = "doc_intel"
                person = doc_info.person
            elif doc_info.doc_type:
                doc_type = doc_info.doc_type
                cat = DOC_TYPE_TO_CATEGORY.get(doc_info.doc_type, cat)
                sub = doc_info.doc_type
                conf = max(conf, doc_info.confidence)
                reason = doc_info.reason
                method = "doc_intel"
                person = doc_info.person or detect_person(f, getattr(cfg, "people", []))

        # Check if verdict has context_path (from RuleEngine or LLM)
        if not context_path and getattr(verdict, "context_path", None):
            context_path = list(verdict.context_path)
            discovered_topic = getattr(verdict, "topic", "") or verdict.category
            discovered_subtopic = getattr(verdict, "subtopic", "") or verdict.subcategory
            cat = discovered_topic
            sub = discovered_subtopic or discovered_topic
            conf = max(conf, verdict.confidence)
            reason = verdict.reason
            method = verdict.method
            if not person:
                p_cand, _, is_prio = detect_person_from_filename_or_path(f.name, f.rel_dir, getattr(cfg, "people", []))
                if is_prio:
                    person = p_cand

        # ---------------------------------------------------------
        # 2. WhatsApp Junk Isolation (Greetings, Memes, Forwards)
        # ---------------------------------------------------------
        if not doc_type and not context_path and getattr(cfg, "separate_whatsapp_junk", True):
            if photo_res and photo_res.is_junk:
                is_junk = True
                cat = "WhatsApp Junk"
                sub = photo_res.junk_type
                conf = max(conf, photo_res.confidence)
                reason = photo_res.reason
                method = "photo_intel"
            elif {"whatsapp_junk", "greeting"} & hints:
                is_junk = True
                cat = "WhatsApp Junk"
                sub = "Greetings"
                conf = 0.95
                reason = "WhatsApp greeting clutter isolated"
                method = "photo_intel"
            elif "meme" in hints:
                is_junk = True
                cat = "WhatsApp Junk"
                sub = "Memes"
                conf = 0.92
                reason = "WhatsApp meme clutter isolated"
                method = "photo_intel"

        # ---------------------------------------------------------
        # 3. Personal Photo Face Clustering & Recognition
        # ---------------------------------------------------------
        if not is_junk and not doc_type and is_photo:
            if photo_res and photo_res.person:
                person = photo_res.person
                cat = "Media Library"
                sub = "Photos"
                conf = max(conf, photo_res.confidence)
                reason = photo_res.reason
                method = "face_recognition"
            else:
                person = detect_person(f, getattr(cfg, "people", []))

        if not person and not is_junk and not is_photo and not context_path:
            person = detect_person(f, getattr(cfg, "people", []))

        # Check dynamic contextual topic fallback if still unassigned
        if not context_path and not doc_type and not is_junk and not is_photo and not f.is_dir:
            ctx = extract_contextual_topic(f.name, f.text, f.rel_dir, getattr(cfg, "people", []))
            if ctx.confidence >= 0.80:
                context_path = list(ctx.context_path)
                discovered_topic = ctx.topic
                discovered_subtopic = ctx.subtopic
                cat = ctx.topic
                sub = ctx.subtopic or ctx.topic
                conf = max(conf, ctx.confidence)
                reason = ctx.reason
                method = "doc_intel"
                if not person:
                    p_cand, _, is_prio = detect_person_from_filename_or_path(f.name, f.rel_dir, getattr(cfg, "people", []))
                    if is_prio:
                        person = p_cand

        status = "ready"
        if conf < cfg.confidence_threshold:
            cat, sub = "Unsorted", "Needs Review"
            status = "low_confidence"

        src = Path(f.path)

        # ---- Person-first family brain ----------------------------------
        # When enabled it owns the destination completely: the folder path is
        # synthesised from the owner + content evidence, not from a fixed tree.
        if family is not None and family.enabled and not f.is_dir:
            fam = family_route(
                cfg, family, f, doc_info, photo_res, verdict, detected_person=person,
                folder_label=label_learner.label_for(f.id) if label_learner else "",
            )
            if fam.path_parts:
                family_dest = route_to_destination(cfg, fam, f.name)
                if fam.confidence >= cfg.confidence_threshold and not fam.is_unknown:
                    person = fam.person or person
                    cat = fam.category or cat
                    sub = fam.subcategory or sub
                    conf = max(conf, fam.confidence)
                    reason = fam.reason or reason
                    method = fam.method
                    if status == "low_confidence":
                        status = "ready"
                else:
                    # Unknown owner: keep it visible for review, never guess.
                    cat, sub = "Others", fam.subcategory or "Review"
                    conf = min(conf or fam.confidence, fam.confidence)
                    reason = fam.reason or reason
                    method = fam.method
                    if status == "ready":
                        status = "low_confidence"

        dest = family_dest or _destination(
            cfg, cat, sub, f.name,
            person=person, doc_type=doc_type, is_photo=is_photo, is_junk=is_junk,
            context_path=context_path,
        )

        if f.is_dir and not cfg.move_projects:
            is_bundle = getattr(f, "kind", "") == "Document bundle"
            if not (is_bundle and cfg.move_bundles):
                dest = src
                status = "protected"
            else:
                key = str(dest).lower()
                if key in seen_dest:
                    seen_dest[key] += 1
                    dest = _dedupe(dest, seen_dest[key])
                else:
                    seen_dest[key] = 1
                if dest.exists() and not _same_file(src, dest):
                    dest = _dedupe(dest, seen_dest[key] + 1)
                    if status == "ready":
                        status = "conflict"
        else:
            key = str(dest).lower()
            if key in seen_dest:
                seen_dest[key] += 1
                dest = _dedupe(dest, seen_dest[key])
            else:
                seen_dest[key] = 1
            if dest.exists() and not _same_file(src, dest):
                dest = _dedupe(dest, seen_dest[key] + 1)
                if status == "ready":
                    status = "conflict"

        items.append(
            PlanItem(
                id=f.id,
                source=f.path,
                destination=str(dest),
                category=cat,
                subcategory=sub,
                confidence=round(conf, 2),
                reason=reason,
                method=method,
                size=f.size,
                mtime=f.mtime,
                status=status,
                is_dir=f.is_dir,
                person=person,
                topic=discovered_topic or (family_dest.parent.name if family_dest else ""),
                context_path=context_path,
            )
        )
        if progress:
            progress(idx + 1, len(files))

    # ---- exact duplicate detection -------------------------------------
    # Only files that share a size are hashed, so a big scan stays fast.
    if getattr(cfg, "detect_duplicates", True):
        by_size: dict[int, list[PlanItem]] = defaultdict(list)
        for item in items:
            if not item.is_dir and item.size >= 1024 and item.status not in {"protected"}:
                by_size[item.size].append(item)
        first_by_hash: dict[tuple[int, str], PlanItem] = {}
        dup_folder = cfg.vault / safe_name(getattr(cfg, "duplicate_folder", "Others")) / "Duplicates"
        for size, group in by_size.items():
            if len(group) < 2:
                continue
            for item in group:
                try:
                    digest = hash_file(Path(item.source))
                except Exception:
                    digest = None
                if not digest:
                    continue
                key = (size, digest)
                first = first_by_hash.get(key)
                if first is None:
                    first_by_hash[key] = item
                    continue
                target = dup_folder if cfg.family_layout else (cfg.vault / "Duplicates")
                dest = target / safe_name(Path(item.source).name)
                k = str(dest).lower()
                if k in seen_dest:
                    seen_dest[k] += 1
                    dest = _dedupe(dest, seen_dest[k])
                else:
                    seen_dest[k] = 1
                item.destination = str(dest)
                item.category = "Others"
                item.subcategory = "Duplicates"
                item.person = ""
                item.status = "duplicate"
                item.method = "duplicate"
                item.reason = f"exact duplicate of {Path(first.source).name}"
                item.duplicate_of = first.source

    stats = {
        "total": len(items),
        "llm_labeled": llm_used,
        "rules_labeled": len(items) - llm_used,
        "llm_error": llm_error,
        "llm_available": cfg.llm.usable,
        "low_confidence": sum(1 for i in items if i.status == "low_confidence"),
        "conflicts": sum(1 for i in items if i.status == "conflict"),
        "protected": sum(1 for i in items if i.status == "protected"),
        "duplicates": sum(1 for i in items if i.status == "duplicate"),
        "bytes": sum(i.size for i in items),
    }
    return items, stats


def _destination(
    cfg: Config,
    category: str,
    subcategory: str,
    filename: str,
    person: str = "",
    doc_type: str = "",
    is_photo: bool = False,
    is_junk: bool = False,
    context_path: list[str] | None = None,
) -> Path:
    cat_s = safe_name(category)
    sub_s = safe_name(subcategory)
    fn_s = safe_name(filename)
    ext_s = Path(filename).suffix.lstrip(".").lower()
    p_s = safe_name(person) if person else ""

    # 1. WhatsApp Junk goes to designated junk directory
    if is_junk or category == "WhatsApp Junk":
        rel = f"WhatsApp_Junk/{sub_s}/{fn_s}"
        return cfg.vault / Path(rel)

    # 2. Dynamic Contextual Folder Creation (On-The-Spot hierarchy synthesis)
    if context_path and getattr(cfg, "dynamic_context_folders", True):
        ctx_parts = [safe_name(p) for p in context_path if p]
        if ctx_parts:
            if getattr(cfg, "person_first_layout", True) and p_s:
                rel = f"{p_s}/{'/'.join(ctx_parts)}/{fn_s}"
                return cfg.vault / Path(rel)
            elif "{person}" in cfg.layout:
                person_folder = p_s or "Shared"
                rel = f"{person_folder}/{'/'.join(ctx_parts)}/{fn_s}"
                return cfg.vault / Path(rel)
            else:
                rel = f"{'/'.join(ctx_parts)}/{fn_s}"
                return cfg.vault / Path(rel)

    DOC_FOLDER_MAP = {
        "Resume": "Resume",
        "Biometrics": "Biometrics",
        "Education": "Education",
        "Health": "Health",
        "Salary": "Salary",
        "Taxes": "Taxes",
        "Banking": "Banking",
        "Legal": "Legal",
        "Resumes & CVs": "Resume",
        "Identity & Certificates": "Biometrics",
        "Health & Medical": "Health",
        "Salary & Employment": "Salary",
        "Banking & Statements": "Banking",
        "Contracts & Legal": "Legal",
    }

    # 2. Person-first organization when person is identified
    if getattr(cfg, "person_first_layout", True) and p_s:
        # Document subfolder (Resume, Biometrics, Education, Health, Salary, etc.)
        if doc_type in DOC_FOLDER_MAP:
            folder = DOC_FOLDER_MAP[doc_type]
            rel = f"{p_s}/{folder}/{fn_s}"
            return cfg.vault / Path(rel)
        if subcategory in DOC_FOLDER_MAP:
            folder = DOC_FOLDER_MAP[subcategory]
            rel = f"{p_s}/{folder}/{fn_s}"
            return cfg.vault / Path(rel)
        # Personal photos with identified person
        if is_photo or (category == "Media Library" and subcategory == "Photos"):
            rel = f"{p_s}/Photos/{fn_s}"
            return cfg.vault / Path(rel)

    # 3. Explicit {person} pattern in layout
    if "{person}" in cfg.layout:
        rel = cfg.layout.format(
            category=cat_s,
            subcategory=sub_s,
            filename=fn_s,
            ext=ext_s,
            person=p_s or "Shared",
        )
    elif p_s and (category in {"Money & Paperwork", "Personal & Life", "Work & Clients"} or (category == "Media Library" and subcategory == "Photos")):
        rel = f"{cat_s}/{sub_s}/{p_s}/{fn_s}"
    else:
        rel = cfg.layout.format(
            category=cat_s,
            subcategory=sub_s,
            filename=fn_s,
            ext=ext_s,
        )
    return cfg.vault / Path(rel)


def _dedupe(dest: Path, n: int) -> Path:
    stem, suffix = dest.stem, dest.suffix
    return dest.with_name(f"{stem} ({n}){suffix}")


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def to_json(items: list[PlanItem]) -> list[dict]:
    return [asdict(i) for i in items]
