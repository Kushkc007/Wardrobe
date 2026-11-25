"""Build a move plan with zero-config automated person detection and strict isolation."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path

from .config import Config
from .llm import classify as llm_classify
from .rules import (
    RuleEngine, Verdict, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS,
    DOCUMENT_EXTENSIONS, ARCHIVE_EXTENSIONS, INSTALLER_EXTENSIONS, CODE_EXTENSIONS
)
from .scanner import FileInfo

RESERVED = set('<>:"/\\|?*')

COMMON_STOPWORDS = {
    'passport', 'aadhaar', 'aadhar', 'pan', 'card', 'resume', 'cv', 'biodata',
    'salary', 'slip', 'payslip', 'marksheet', 'certificate', 'degree', 'diploma',
    'transcript', 'bill', 'invoice', 'receipt', 'statement', 'bank', 'tax',
    'itr', 'form16', 'form', 'report', 'medical', 'prescription', 'lab',
    'photo', 'pic', 'img', 'image', 'picture', 'wallpaper', 'screenshot',
    'screen', 'capture', 'shot', 'video', 'vid', 'clip', 'recording',
    'audio', 'music', 'song', 'doc', 'pdf', 'jpg', 'png', 'jpeg', 'docx',
    'final', 'new', 'old', 'copy', 'scan', 'scanned', 'official', 'signed',
    'download', 'downloads', 'desktop', 'documents', 'books', 'notes', 'files',
    'january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
    'september', 'october', 'november', 'december', 'jan', 'feb', 'mar', 'apr',
    'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec', '2020', '2021', '2022',
    '2023', '2024', '2025', '2026', 'update', 'draft', 'version', 'v1', 'v2',
    'introduction', 'intro', 'algorithms', 'desktop', 'installer', 'setup',
    'free', 'docker', 'system', 'windows', 'electricity', 'water', 'gas',
    'wifi', 'broadband', 'rent', 'maintenance', 'utility', 'general'
}

KINSHIP = {
    'papa', 'mummy', 'mom', 'dad', 'bhai', 'didi', 'brother', 'sister',
    'baby', 'nanu', 'dadi', 'chacha', 'chachi', 'mama', 'mami'
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


def safe_name(name: str) -> str:
    cleaned = "".join("_" if c in RESERVED else c for c in name).strip(" .")
    return cleaned or "unnamed"


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

    # 2. Kinship names (Papa, Mummy, Dad, Mom, Bhai, Didi, etc.)
    for k in KINSHIP:
        pat = r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])"
        if re.search(pat, name_low) or re.search(pat, rel_low):
            return k.capitalize()

    # 3. Dynamic Folder Provenance: e.g. 'Downloads/Govind/file.pdf' or 'Pictures/Kush/photo.jpg'
    parts = re.split(r"[\\/]", f.rel_dir)
    for part in reversed(parts):
        cleaned = re.sub(r"[^a-zA-Z]", "", part).strip()
        if cleaned.lower() not in COMMON_STOPWORDS and 2 <= len(cleaned) <= 20:
            if cleaned.lower() not in {
                'users', 'user', 'windows', 'system', 'appdata', 'program', 'programdata',
                'temp', 'tmp', 'downloads', 'desktop', 'documents', 'pictures', 'videos',
                'music', 'onedrive', 'organized', 'project', 'projects', 'repos', 'repo'
            }:
                return cleaned.capitalize()

    # 4. Proper noun extraction from filename (e.g. 'Passport Govind', 'Jaycon Salary Slip', 'Kush Resume')
    stem = Path(f.name).stem
    tokens = re.split(r"[^a-zA-Z0-9]+", stem)
    candidates = []
    for t in tokens:
        if not t or t.isdigit():
            continue
        t_low = t.lower()
        if t_low in COMMON_STOPWORDS:
            continue
        if len(t) < 3 or len(t) > 20:
            continue
        candidates.append(t.capitalize())

    if candidates:
        return candidates[0]

    # 5. Extract from text header (e.g. 'Name: Govind Sharma', 'Candidate: Kush')
    text = (f.text or "")[:1500]
    if text:
        m = re.search(r"(?:Name|Employee Name|Candidate|Candidate Name|Patient Name)\s*[:\-]\s*([A-Z][a-z]+)", text, re.IGNORECASE)
        if m:
            cand = m.group(1).capitalize()
            if cand.lower() not in COMMON_STOPWORDS:
                return cand

    return ""


def build_plan(
    cfg: Config,
    files: list[FileInfo],
    taxonomy: dict,
    use_llm: bool = True,
    progress=None,
) -> tuple[list[PlanItem], dict]:
    """Return (plan items, stats)."""
    engine = RuleEngine(taxonomy, cfg.fallback)
    verdicts: dict[str, Verdict] = {}
    llm_error = ""
    llm_used = 0

    if use_llm and cfg.llm.usable:
        result = llm_classify(cfg, taxonomy, files)
        verdicts.update(result.verdicts)
        llm_used = len(result.verdicts)
        llm_error = result.error

    items: list[PlanItem] = []
    seen_dest: dict[str, int] = {}

    for idx, f in enumerate(files):
        verdict = verdicts.get(f.id)
        if verdict is None:
            verdict = engine.classify(f)

        cat = verdict.category
        sub = verdict.subcategory
        status = "ready"
        if verdict.confidence < cfg.confidence_threshold:
            cat, sub = "Unsorted", "Needs Review"
            status = "low_confidence"

        src = Path(f.path)
        person = detect_person(f, getattr(cfg, "people", []))
        dest = _destination(cfg, cat, sub, f.name, person=person)

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
                confidence=verdict.confidence,
                reason=verdict.reason,
                method=verdict.method,
                size=f.size,
                mtime=f.mtime,
                status=status,
                is_dir=f.is_dir,
                person=person,
            )
        )
        if progress:
            progress(idx + 1, len(files))

    stats = {
        "total": len(items),
        "llm_labeled": llm_used,
        "rules_labeled": len(items) - llm_used,
        "llm_error": llm_error,
        "llm_available": cfg.llm.usable,
        "low_confidence": sum(1 for i in items if i.status == "low_confidence"),
        "conflicts": sum(1 for i in items if i.status == "conflict"),
        "protected": sum(1 for i in items if i.status == "protected"),
        "bytes": sum(i.size for i in items),
    }
    return items, stats


def _destination(cfg: Config, category: str, subcategory: str, filename: str, person: str = "") -> Path:
    cat_s = safe_name(category)
    sub_s = safe_name(subcategory)
    fn_s = safe_name(filename)
    ext_s = Path(filename).suffix.lstrip(".").lower()
    p_s = safe_name(person) if person else ""

    if "{person}" in cfg.layout:
        rel = cfg.layout.format(
            category=cat_s,
            subcategory=sub_s,
            filename=fn_s,
            ext=ext_s,
            person=p_s or "Shared",
        )
    elif p_s and (category in {"Money & Paperwork", "Personal & Life", "Work & Clients"} or (category == "Media Library" and subcategory == "Photos")):
        # Auto person separation for paperwork, IDs, and personal photos!
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
