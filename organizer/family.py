"""Family Brain - person-first, user-defined routing with dynamic folder synthesis.

This module answers two questions for every file:

    1. WHO does it belong to?        -> a person, "Common", or "Others"
    2. WHAT is it, in human terms?   -> e.g. Photos/Trips/Amritsar,
                                        Documents/Salary Slips/R1, Documents/Government IDs/Aadhaar

Nothing about a family is hard-coded. People, aliases, relationships,
employers and custom routing rules all live in ``family.json`` and are edited
from the dashboard. The engine only contains *how to think*:

    - profile name / alias / kinship / employer hit  -> strong ownership
    - document intelligence (resume header, Aadhaar, PAN, ...) -> strong ownership
    - face recognition club result                   -> strong ownership
    - filename / folder provenance                   -> supporting evidence
    - conflicting evidence                           -> "Others/Review", never a guess

The folder path is synthesized on the spot from the evidence. ``apply_plan``
already creates every missing parent folder, so a brand-new category (a new
trip, a new company, a new event) appears exactly when the first file needs it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .scanner import FileInfo

# ---------------------------------------------------------------------------
#  Vocabulary (structure, not family data). These are only fallbacks used when
#  the user has not defined anything; profile rules always win.
# ---------------------------------------------------------------------------

PHOTO_EXTS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".bmp",
    ".tiff", ".tif", ".avif", ".raw", ".cr2", ".nef", ".dng", ".arw",
}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".wmv", ".m4v", ".webm", ".flv", ".3gp", ".ts", ".vob"}
AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".opus", ".wav", ".aiff", ".mid", ".midi"}
BOOK_EXTS = {".epub", ".mobi", ".azw3", ".azw", ".fb2", ".djvu", ".cbz", ".cbr"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".iso", ".cab", ".dmg"}
INSTALLER_EXTS = {".exe", ".msi", ".msix", ".appx", ".apk", ".deb", ".rpm"}

KINSHIP_WORDS = {
    "papa": "Father", "dad": "Father", "father": "Father", "daddy": "Father", "pitaji": "Father",
    "mummy": "Mother", "mom": "Mother", "mother": "Mother", "mataji": "Mother", "maa": "Mother",
    "bhai": "Brother", "bhaiya": "Brother", "brother": "Brother", "behen": "Sister",
    "didi": "Sister", "sister": "Sister",
    "bua": "Bua", "buaji": "Bua", "chacha": "Chacha", "chachi": "Chachi",
    "mama": "Mama", "mami": "Mami", "dada": "Grandfather", "dadi": "Grandmother",
    "nanu": "Grandfather", "nani": "Grandmother", "beta": "Son", "beti": "Daughter",
    "wife": "Wife", "husband": "Husband", "son": "Son", "daughter": "Daughter",
}

GREETING_WORDS = {
    "good morning", "goodmorning", "morning wishes", "gm", "suprabhat",
    "good night", "goodnight", "gn", "shubh ratri",
    "good evening", "good afternoon", "greeting", "greetings", "wishes",
}
FESTIVAL_WORDS = {
    "diwali", "deepawali", "holi", "eid", "christmas", "new year", "newyear",
    "rakhi", "raksha bandhan", "dussehra", "dasara", "navratri", "navaratri",
    "janmashtami", "ganesh chaturthi", "baisakhi", "lohri", "onam", "pongal",
    "thanksgiving", "halloween", "valentine", "mother's day", "father's day",
}
JOKE_WORDS = {"joke", "jokes", "chutkule", "funny", "meme", "memes", "humor", "lol", "forward"}
PASSWORD_WORDS = {"password", "passwords", "credentials", "login", "logins", "secret", "secrets", "keychain"}
SCREENSHOT_WORDS = {"screenshot", "screen shot", "screencap", "screen capture", "snip", "capture"}

EVENT_WORDS = [
    "wedding", "shaadi", "sadi", "marriage", "reception", "engagement",
    "haldi", "mehndi", "mehendi", "sangeet", "baraat", "nikah", "roka",
    "birthday", "anniversary", "function", "pooja", "puja", "ceremony",
    "naming", "mundan", "housewarming", "griha pravesh",
]
TRIP_WORDS = {"trip", "tour", "travel", "vacation", "holiday", "visit", "yatra", "trek", "hike"}
SPORT_WORDS = {"batting", "cricket", "football", "soccer", "match", "practice", "gym", "cycling", "running", "marathon", "tennis", "badminton"}

PROJECT_WORDS = {"project", "office work", "vendor", "client", "invoice", "quotation", "report", "presentation", "proposal"}

PROJECT_WORDS = {"project", "office work", "vendor", "client", "invoice", "quotation", "report", "presentation", "proposal"}

# Folder labels are *derived from the file's own evidence*. This vocabulary is
# only a normaliser so "payslip" and "salary slip" land in one folder; the tree
# itself is never predefined and every new label becomes a new folder on the fly.
LABEL_HINTS = [
    ("salary slip", "Salary Slip"), ("payslip", "Payslip"), ("pay slip", "Pay Slip"),
    ("aadhaar", "Aadhaar"), ("aadhar", "Aadhaar"),
    ("pan card", "PAN"), ("passport", "Passport"),
    ("driving licence", "Driving Licence"), ("driving license", "Driving License"),
    ("voter", "Voter ID"), ("ration card", "Ration Card"),
    ("signature", "Signature"), ("thumb impression", "Thumb Impression"),
    ("fingerprint", "Fingerprint"),
    ("sale deed", "Sale Deed"), ("rent agreement", "Rent Agreement"),
    ("registry", "Registry"), ("property", "Property"),
    ("insurance", "Insurance"), ("mediclaim", "Mediclaim"), ("lic", "LIC Policy"),
    ("prescription", "Prescription"), ("lab report", "Lab Report"),
    ("medical", "Medical Report"), ("diagnosis", "Medical Report"),
    ("marksheet", "Marksheet"), ("degree", "Degree"), ("diploma", "Diploma"),
    ("certificate", "Certificate"), ("certification", "Certification"),
    ("course", "Course"), ("offer letter", "Offer Letter"),
    ("appointment letter", "Appointment Letter"), ("experience letter", "Experience Letter"),
    ("relieving letter", "Relieving Letter"), ("form 16", "Form 16"),
    ("form16", "Form 16"), ("itr", "ITR"), ("tax return", "Tax Return"),
    ("bank statement", "Bank Statement"), ("passbook", "Passbook"), ("cheque", "Cheque"),
    ("invoice", "Invoice"), ("receipt", "Receipt"), ("quotation", "Quotation"),
    ("resume", "Resume"), ("curriculum vitae", "Resume"), ("biodata", "Resume"),
]
SCENERY_HINTS = {"landscape", "scenery", "nature", "mountain", "beach", "sunset", "sunrise", "sky", "garden"}

SAFE_STRIP = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
TOKEN_RE = re.compile(r"[a-z0-9]+")
CAMEL_RE = re.compile(r"[A-Z][a-z0-9]+")

GENERIC_TOKENS = {
    "img", "image", "photo", "pic", "picture", "dsc", "dcim", "vid", "video",
    "whatsapp", "wa", "screenshot", "screen", "shot", "capture", "new", "old",
    "final", "copy", "edit", "edited", "original", "download", "downloads",
    "file", "doc", "document", "scan", "scanned", "page", "part", "version",
    "the", "and", "with", "from", "for", "trip", "tour", "travel", "vacation",
    "holiday", "visit", "jpeg", "jpg", "png", "pdf", "docx", "xlsx", "mp4",
    "mov", "heic", "webp", "jfif", "2020", "2021", "2022", "2023", "2024",
    "2025", "2026", "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
    "sep", "oct", "nov", "dec",
}


# ---------------------------------------------------------------------------
#  Profile
# ---------------------------------------------------------------------------

@dataclass
class PersonProfile:
    name: str
    relationship: str = ""
    aliases: list[str] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    notes: str = ""

    def all_names(self) -> list[str]:
        names = [self.name, *self.aliases]
        if self.relationship:
            names.append(self.relationship)
        return [n.strip() for n in names if n and n.strip()]


@dataclass
class FamilyRule:
    """A user-defined override: "if a file mentions X, it belongs to Y"."""
    match: list[str] = field(default_factory=list)
    person: str = ""
    section: str = ""          # Photos | Documents | Common | Others
    path: list[str] = field(default_factory=list)
    confidence: float = 0.98


@dataclass
class FamilyProfile:
    enabled: bool = True
    people: list[PersonProfile] = field(default_factory=list)
    rules: list[FamilyRule] = field(default_factory=list)
    common_folder: str = "Common"
    unknown_folder: str = "Others"
    shared_album: str = "Family & Friends"

    def person_names(self) -> list[str]:
        return [p.name for p in self.people]

    def resolve(self, candidate: str) -> PersonProfile | None:
        """Match a detected name/alias/kinship to a configured person."""
        if not candidate:
            return None
        low = candidate.strip().lower()
        for p in self.people:
            for n in p.all_names():
                if n.lower() == low:
                    return p
        # token containment both ways: "Manoj Kumar" vs "Manoj Kumar Chaturvedi"
        for p in self.people:
            for n in p.all_names():
                nl = n.lower()
                if len(nl) >= 4 and (nl in low or low in nl):
                    return p
        return None


def profile_path(cfg) -> Path:
    return getattr(cfg, "family_profile_path", cfg.app_dir / "family.json")


def load_profile(cfg) -> FamilyProfile:
    path = profile_path(cfg)
    if not path.exists():
        return FamilyProfile()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return FamilyProfile()

    people = []
    for p in raw.get("people", []):
        if isinstance(p, str):
            p = {"name": p}
        name = str(p.get("name", "")).strip()
        if not name:
            continue
        people.append(PersonProfile(
            name=name,
            relationship=str(p.get("relationship", "")).strip(),
            aliases=_strlist(p.get("aliases")),
            companies=_strlist(p.get("companies")),
            keywords=_strlist(p.get("keywords")),
            notes=str(p.get("notes", "")),
        ))
    rules = []
    for r in raw.get("rules", []):
        if not isinstance(r, dict):
            continue
        rules.append(FamilyRule(
            match=_strlist(r.get("match")),
            person=str(r.get("person", "")).strip(),
            section=str(r.get("section", "")).strip(),
            path=_strlist(r.get("path")),
            confidence=float(r.get("confidence", 0.98)),
        ))
    return FamilyProfile(
        enabled=bool(raw.get("enabled", True)),
        people=people,
        rules=rules,
        common_folder=str(raw.get("common_folder", "Common")).strip() or "Common",
        unknown_folder=str(raw.get("unknown_folder", "Others")).strip() or "Others",
        shared_album=str(raw.get("shared_album", "Family & Friends")).strip() or "Family & Friends",
    )


def save_profile(cfg, data: dict) -> FamilyProfile:
    path = profile_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    # validate / normalise through the same loader schema
    clean = {
        "version": 1,
        "enabled": bool(data.get("enabled", True)),
        "common_folder": str(data.get("common_folder", "Common")).strip() or "Common",
        "unknown_folder": str(data.get("unknown_folder", "Others")).strip() or "Others",
        "shared_album": str(data.get("shared_album", "Family & Friends")).strip() or "Family & Friends",
        "people": [],
        "rules": [],
    }
    for p in data.get("people", []):
        if isinstance(p, str):
            p = {"name": p}
        name = str(p.get("name", "")).strip()
        if not name:
            continue
        clean["people"].append({
            "name": name,
            "relationship": str(p.get("relationship", "")).strip(),
            "aliases": _strlist(p.get("aliases")),
            "companies": _strlist(p.get("companies")),
            "keywords": _strlist(p.get("keywords")),
            "notes": str(p.get("notes", "")),
        })
    for r in data.get("rules", []):
        if not isinstance(r, dict):
            continue
        match = _strlist(r.get("match"))
        if not match:
            continue
        clean["rules"].append({
            "match": match,
            "person": str(r.get("person", "")).strip(),
            "section": str(r.get("section", "")).strip(),
            "path": _strlist(r.get("path")),
            "confidence": float(r.get("confidence", 0.98)),
        })
    path.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    return load_profile(cfg)


def _strlist(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"[,;\n]", value) if v.strip()]
    return [str(v).strip() for v in value if str(v).strip()]


# ---------------------------------------------------------------------------
#  Route
# ---------------------------------------------------------------------------

@dataclass
class FamilyRoute:
    person: str = ""
    path_parts: list[str] = field(default_factory=list)
    section: str = ""
    category: str = ""
    subcategory: str = ""
    confidence: float = 0.0
    reason: str = ""
    method: str = "family"
    is_common: bool = False
    is_unknown: bool = False
    company: str = ""

    @property
    def folder(self) -> str:
        return "/".join(self.path_parts)


def route_file(
    cfg,
    profile: FamilyProfile,
    f: FileInfo,
    doc_info=None,
    photo=None,
    verdict=None,
    detected_person: str = "",
    folder_label: str = "",
) -> FamilyRoute:
    """Decide the owner and the human folder hierarchy for one file."""
    name = f.name
    fn_low = name.lower()
    folder_low = (f.rel_dir or "").lower()
    text = getattr(f, "text", "") or ""
    text_low = text[:20000].lower()
    hints = {h.lower() for h in (getattr(f, "hints", None) or [])}
    ext = f.ext.lower()
    hay_name = f"{fn_low} {folder_low}"
    hay_all = f"{hay_name} {text_low}"

    # ---- 0. user-defined hard rules win over everything -------------------
    for rule in profile.rules:
        if rule.match and all(_phrase_hit(m, hay_name) for m in rule.match):
            person = profile.resolve(rule.person)
            if person:
                parts = [safe_folder(person.name), *[safe_folder(x) for x in rule.path]]
                return FamilyRoute(
                    person=person.name, path_parts=parts,
                    section=(rule.section or (rule.path[0] if rule.path else "Documents")),
                    category=rule.section or (rule.path[0] if rule.path else "Documents"),
                    subcategory="/".join(rule.path[1:]) or rule.section,
                    confidence=rule.confidence,
                    reason=f"user rule matched: {', '.join(rule.match)}",
                    method="family_rule", company=_company_for(profile, person, hay_all),
                )

    # ---- 1. Common / shared material (checked before people only when it
    #         cannot be a personal document) --------------------------------
    doc_type = getattr(doc_info, "doc_type", "") if doc_info else ""
    subtype = getattr(doc_info, "subtype", "") if doc_info else ""

    common = _common_route(cfg, profile, f, fn_low, hay_all, text_low, hints, photo, doc_type)
    if common is not None:
        return common

    # ---- 2. Ownership evidence -------------------------------------------
    owner, owner_conf, owner_reason, owner_method = _detect_owner(
        profile, f, doc_info, photo, hay_name, hay_all, text_low, detected_person
    )

    # ---- 3. Content kind --------------------------------------------------
    company = _detect_company(profile, owner, hay_name, hay_all, doc_info)
    owner_profile = profile.resolve(owner) if owner else None
    owner_names = owner_profile.all_names() if owner_profile else ([owner] if owner else [])
    domain = _domain_route(
        cfg, profile, f, ext, fn_low, hay_all, text_low, hints,
        doc_type, subtype, doc_info, photo, owner, company, owner_conf, owner_names,
        folder_label,
    )

    if owner and domain is not None:
        parts = [safe_folder(owner), *domain]
        return FamilyRoute(
            person=owner, path_parts=parts, section=domain[0],
            category=domain[0], subcategory="/".join(domain[1:]) or domain[0],
            confidence=min(0.99, owner_conf), reason=owner_reason,
            method=owner_method, company=company,
        )

    # A shared object that simply has no person attached. Photos, projects,
    # videos and music are family-wide material, not "unknown".
    common_name = safe_folder(profile.common_folder)
    if domain is not None and not owner and (domain[0] == common_name or domain[0] in {"Photos", "Videos", "Music"}):
        parts = domain if domain[0] == common_name else [common_name, *domain]
        return FamilyRoute(
            person="", path_parts=parts, section="Common", is_common=True,
            category="Common", subcategory="/".join(domain[1:]) or domain[0],
            confidence=0.72, reason="shared material with no identifiable family member",
            method="family_common", company=company,
        )

    # ---- 4. Unknown owner: still file it by kind, never guess a person ----
    parts = [safe_folder(profile.unknown_folder), *_unknown_domain(ext, hints, domain)]
    return FamilyRoute(
        person=owner, path_parts=parts, section="Others", is_unknown=True,
        category="Others", subcategory="/".join(parts[1:]) or "Review",
        confidence=max(0.35, min(owner_conf, 0.5)),
        reason=owner_reason or "no reliable family member match - kept for review",
        method="family_review",
    )


# ---------------------------------------------------------------------------
#  Ownership
# ---------------------------------------------------------------------------

def _detect_owner(
    profile: FamilyProfile,
    f: FileInfo,
    doc_info,
    photo,
    hay_name: str,
    hay_all: str,
    text_low: str,
    detected_person: str = "",
) -> tuple[str, float, str, str]:
    """Score every person against the evidence and return the clearest owner."""
    scores: dict[str, float] = {}
    reasons: dict[str, str] = {}
    methods: dict[str, str] = {}

    def bump(name: str, score: float, reason: str, method: str):
        if score > scores.get(name, 0):
            scores[name] = score
            reasons[name] = reason
            methods[name] = method

    for p in profile.people:
        # exact profile names / aliases / relationship
        for token in p.all_names():
            tl = token.lower()
            if len(tl) < 2:
                continue
            if _phrase_hit(tl, hay_name):
                bump(p.name, 0.94, f"name/alias '{token}' in filename or folder", "family_alias")
            elif _phrase_hit(tl, text_low):
                bump(p.name, 0.88, f"name/alias '{token}' inside document text", "family_alias")

        # employers are extremely strong: "R1", "Mahagun", ...
        for company in p.companies:
            cl = company.lower()
            if len(cl) < 2:
                continue
            if _phrase_hit(cl, hay_name):
                bump(p.name, 0.95, f"employer '{company}' in filename or folder", "family_company")
            elif _phrase_hit(cl, text_low):
                bump(p.name, 0.88, f"employer '{company}' inside document", "family_company")

        # custom keywords the user attached to this person
        for kw in p.keywords:
            kl = kw.lower()
            if kl and _phrase_hit(kl, hay_all):
                bump(p.name, 0.9, f"user keyword '{kw}'", "family_keyword")

    # document intelligence / face club results. When the family profile does
    # not know the name yet we still trust a confident detector: this keeps
    # zero-config sorting working, and the dashboard can add the person later.
    for candidate, conf, why, method in (
        (getattr(doc_info, "person", "") if doc_info else "", 0.93, "document intelligence identified the holder", "family_doc"),
        (getattr(photo, "person", "") if photo else "", 0.9, "face recognition matched the person", "family_face"),
        (detected_person, 0.76, "filename, folder or document context names the person", "family_detect"),
    ):
        if not candidate:
            continue
        p = profile.resolve(candidate)
        if p:
            bump(p.name, conf, why, method)
        else:
            clean = _display_person(candidate)
            if clean:
                bump(clean, conf - 0.05, why, method)

    # folder provenance when the folder is literally somebody's name
    parts = re.split(r"[\\/]", f.rel_dir or "")
    for part in reversed(parts):
        clean = re.sub(r"[^A-Za-z ]", "", part).strip()
        if 2 <= len(clean) <= 25:
            p = profile.resolve(clean)
            if p:
                bump(p.name, 0.8, f"parent folder '{part}' names the person", "family_folder")

    if not scores:
        return "", 0.0, "", "family"

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best_name, best_score = ranked[0]
    if len(ranked) > 1 and best_score - ranked[1][1] < 0.08:
        # genuinely conflicting evidence -> do not guess
        return "", 0.0, "conflicting ownership evidence, left for review", "family_conflict"
    return best_name, best_score, reasons[best_name], methods[best_name]


def _detect_company(profile: FamilyProfile, owner: str, hay_name: str, hay_all: str, doc_info) -> str:
    for p in profile.people:
        if owner and p.name != owner:
            continue
        for c in p.companies:
            if _phrase_hit(c.lower(), hay_all):
                return c
    doc_company = str(getattr(doc_info, "company", "") or "").strip()
    if doc_company:
        return doc_company
    return ""


# ---------------------------------------------------------------------------
#  Common material
# ---------------------------------------------------------------------------

def _common_route(cfg, profile, f, fn_low, hay_all, text_low, hints, photo, doc_type) -> FamilyRoute | None:
    # Screenshots -> Common/Screenshots. A screenshot of a real document still
    # belongs to its person, so doc intelligence keeps priority.
    if not doc_type and ("screenshot" in hints or any(w in fn_low for w in SCREENSHOT_WORDS)):
        return _common(profile, ["Screenshots"], "Screenshots", 0.9, "screen capture")

    # Passwords / credentials
    if any(_phrase_hit(w, hay_all) for w in PASSWORD_WORDS) and f.ext.lower() in {
        ".txt", ".md", ".csv", ".json", ".xlsx", ".xls", ".docx", ".pdf", ".kdbx", ".1pux",
    }:
        return _common(profile, ["Passwords"], "Passwords", 0.92, "password/credential file")

    # Books, no matter who reads them
    if f.ext.lower() in BOOK_EXTS or (
        f.ext.lower() == ".pdf" and any(_phrase_hit(w, fn_low) for w in ("book", "novel", "ebook"))
    ):
        book_title = _title_from_filename(f.name)
        return _common(profile, ["Books", book_title] if book_title else ["Books"],
                       "Books", 0.9, "book / ebook shared by the family")

    # WhatsApp greetings / festival wishes / jokes / memes
    junk_type = getattr(photo, "junk_type", "") if photo else ""
    if junk_type:
        sub = _greeting_folder(junk_type, fn_low, text_low)
        if sub:
            return _common(profile, sub, "/".join(sub[1:]), 0.92, f"shared {junk_type.lower()}")

    if any(_phrase_hit(w, hay_all) for w in GREETING_WORDS):
        blob = _norm(hay_all)
        g = "Good Morning" if any(w in blob for w in ("good morning", "goodmorning", "morning wishes", "suprabhat")) else (
            "Good Night" if any(w in blob for w in ("good night", "goodnight", "shubh ratri", "gn ")) else "Greetings")
        return _common(profile, ["Greetings", g], f"Greetings/{g}", 0.9, "greeting message")

    for fest in FESTIVAL_WORDS:
        if _phrase_hit(fest, hay_all):
            return _common(profile, ["Greetings", "Festivals", fest.title()],
                           f"Greetings/Festivals/{fest.title()}", 0.88, f"festival greeting ({fest})")

    if any(_phrase_hit(w, hay_all) for w in JOKE_WORDS):
        return _common(profile, ["Jokes & Memes"], "Jokes & Memes", 0.88, "joke / meme / forward")

    return None


def _common(profile: FamilyProfile, sub_parts: list[str], subcategory: str,
            conf: float, reason: str) -> FamilyRoute:
    parts = [safe_folder(profile.common_folder), *[safe_folder(p) for p in sub_parts]]
    return FamilyRoute(
        path_parts=parts, section="Common", is_common=True,
        category="Common", subcategory=subcategory,
        confidence=conf, reason=reason, method="family_common",
    )


def _greeting_folder(junk_type: str, fn_low: str, text_low: str) -> list[str]:
    blob = f"{fn_low} {text_low[:2000]}"
    jt = (junk_type or "").lower()
    if "meme" in jt or any(_phrase_hit(w, blob) for w in JOKE_WORDS):
        return ["Jokes & Memes"]
    if any(_phrase_hit(w, blob) for w in ("good night", "goodnight", "shubh ratri")):
        return ["Greetings", "Good Night"]
    if any(_phrase_hit(w, blob) for w in ("good morning", "goodmorning", "morning wishes", "suprabhat")):
        return ["Greetings", "Good Morning"]
    for fest in FESTIVAL_WORDS:
        if _phrase_hit(fest, blob):
            return ["Greetings", "Festivals", fest.title()]
    return ["Greetings", "General"]


# ---------------------------------------------------------------------------
#  Domain (what the file is)
# ---------------------------------------------------------------------------

def _domain_route(
    cfg, profile, f, ext, fn_low, hay_all, text_low, hints,
    doc_type, subtype, doc_info, photo, owner, company, owner_conf,
    owner_names: list[str] | None = None, folder_label: str = "",
) -> list[str] | None:
    """Return the folder path *under* the owner (or under Common).

    No fixed taxonomy: the labels come from the file's own detected type
    (Aadhaar, Payslip, Property, Amritsar, Wedding/Haldi, ...). A label that has
    never been seen before simply becomes a new folder when the file moves.
    """

    # Dynamic project/topic context from document intelligence (NASA, client work)
    context_path = list(getattr(doc_info, "context_path", []) or []) if doc_info else []
    if context_path:
        cleaned = [safe_folder(x) for x in context_path if str(x).strip()]
        if cleaned:
            if owner:
                return cleaned
            return [safe_folder(profile.common_folder), *cleaned]

    # --- documents -------------------------------------------------------
    is_signature = bool(folder_label) and any(
        _phrase_hit(w, hay_all) for w in ("signature", "thumb", "fingerprint")
    )
    if doc_type or is_signature or _looks_like_document(fn_low, hay_all, ext, hints):
        doc_parts = _document_parts(fn_low, hay_all, text_low, ext, doc_type, subtype, company, doc_info, folder_label)
        if doc_parts:
            return doc_parts

    # --- photos ----------------------------------------------------------
    if ext in PHOTO_EXTS:
        return _photo_parts(f, fn_low, hay_all, hints, photo, owner, owner_names or [])

    # --- video / audio ---------------------------------------------------
    if ext in VIDEO_EXTS:
        return _media_parts("Videos", fn_low, hay_all)
    if ext in AUDIO_EXTS:
        return ["Music"]

    # --- archives / installers ------------------------------------------
    if ext in INSTALLER_EXTS:
        return _split("Installers")
    if ext in ARCHIVE_EXTS:
        return _split("Archives")

    # --- unknown but owned ----------------------------------------------
    if owner:
        return ["Other"]

    return None


def _document_parts(fn_low, hay_all, text_low, ext, doc_type, subtype, company,
                    doc_info, folder_label: str = "") -> list[str] | None:
    """Use the on-the-spot label the scan learned for this file.

    Nothing here maps a document to a fixed folder. If the learner gave us a
    label ("Salary Slip", "Sale Deed", "NASA", "Aadhaar", ...) that *is* the
    folder. A detected subtype is only a fallback when the file itself was
    nameless.
    """
    company_part = [safe_folder(company)] if company else []
    if folder_label:
        return [safe_folder(folder_label), *company_part]

    subtype = str(subtype or "").strip()
    if subtype and subtype.lower() not in {"identity id", "biometric"}:
        return [safe_folder(subtype), *company_part]
    if doc_type and str(doc_type).lower() not in {"custom"}:
        return [safe_folder(doc_type), *company_part]

    for word, label in (("signature", "Signature"),
                        ("thumb impression", "Thumb Impression"),
                        ("fingerprint", "Fingerprint")):
        if _phrase_hit(word, hay_all):
            return [label]
    if company:
        return [safe_folder(company)]
    return ["Other"]


def _looks_like_document(fn_low: str, hay_all: str, ext: str, hints=None) -> bool:
    if hints and ({"scan", "document"} & set(hints)):
        return True
    return ext in {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".xls", ".xlsx",
                   ".csv", ".ppt", ".pptx", ".odp", ".pages", ".key"}


def _photo_parts(f: FileInfo, fn_low: str, hay_all: str, hints, photo,
                 owner, owner_names: list[str] | None = None) -> list[str]:
    faces = getattr(photo, "face_count", 0) or 0

    events = [w for w in EVENT_WORDS if _phrase_hit(w, fn_low)]
    if events:
        # first event = main function, second = sub-function (Haldi, Mehndi)
        main = events[0].title().replace("Shaadi", "Wedding").replace("Sadi", "Wedding")
        parts = ["Photos", "Functions", main]
        if len(events) > 1:
            parts.append(events[1].title())
        return parts

    if any(_phrase_hit(w, fn_low) for w in TRIP_WORDS):
        place = _place_from_filename(f.name, owner, owner_names or [])
        return ["Photos", "Trips", place] if place else ["Photos", "Trips"]

    sports = [w for w in SPORT_WORDS if _phrase_hit(w, fn_low)]
    if sports:
        return ["Photos", "Sports", sports[0].title()]

    if faces >= 2 or any(_phrase_hit(w, fn_low) for w in ("family", "group", "friends", "together", "with others")):
        return ["Photos", "With Others"]
    if faces == 1:
        return ["Photos", "Personal"]
    if owner and any(_phrase_hit(w, hay_all) for w in SCENERY_HINTS):
        return ["Photos", "Scenery"]
    if not owner and any(_phrase_hit(w, fn_low) for w in SCENERY_HINTS):
        return ["Photos", "Scenery"]
    if owner:
        return ["Photos", "Personal"]
    return ["Photos", "Unsorted"]


def _media_parts(base: str, fn_low: str, hay_all: str) -> list[str]:
    events = [w for w in EVENT_WORDS if _phrase_hit(w, fn_low)]
    if events:
        return [base, "Events", events[0].title()]
    if any(_phrase_hit(w, fn_low) for w in TRIP_WORDS):
        place = _place_from_filename(fn_low)
        return [base, "Trips", place] if place else [base, "Trips"]
    return [base]


def _unknown_domain(ext: str, hints: set[str], domain: list[str] | None) -> list[str]:
    if domain:
        # keep the kind, drop any person-specific leading folder
        return [safe_folder(p) for p in domain]
    if ext in PHOTO_EXTS:
        return ["Photos", "Review"]
    if ext in VIDEO_EXTS:
        return ["Videos"]
    if ext in AUDIO_EXTS:
        return ["Music"]
    if ext in INSTALLER_EXTS:
        return ["Installers"]
    if ext in ARCHIVE_EXTS:
        return ["Archives"]
    return ["Review"]


# ---------------------------------------------------------------------------
#  Small helpers
# ---------------------------------------------------------------------------

def safe_folder(name: str) -> str:
    cleaned = SAFE_STRIP.sub("", str(name)).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "Unnamed"


def _split(path: str) -> list[str]:
    return [safe_folder(p) for p in path.split("/") if p.strip()]


def _norm(text: str) -> str:
    return re.sub(r"[_\-]+", " ", str(text).lower())


def _phrase_hit(phrase: str, hay: str) -> bool:
    """Word-boundary match after normalising separators (good_morning == good morning)."""
    phrase = _norm(phrase)
    hay = _norm(hay)
    if not phrase or not hay:
        return False
    if " " in phrase or re.search(r"[^a-z0-9]", phrase):
        return phrase in hay
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", hay))


def _company_for(profile: FamilyProfile, person: PersonProfile, hay: str) -> str:
    for c in person.companies:
        if _phrase_hit(c.lower(), hay):
            return c
    return ""


def _display_person(candidate: str) -> str:
    """Turn a raw detector string into a stable folder name."""
    clean = re.sub(r"[^A-Za-z .'\-]", " ", str(candidate)).strip()
    clean = re.sub(r"\s+", " ", clean)
    if not clean or len(clean) < 2 or clean.lower() in GENERIC_TOKENS:
        return ""
    return " ".join(w[:1].upper() + w[1:].lower() for w in clean.split())[:40]


def _title_from_filename(name: str) -> str:
    stem = Path(name).stem
    tokens = [t for t in re.split(r"[_\-. ]+", stem) if t and t.lower() not in GENERIC_TOKENS]
    if not tokens:
        return ""
    return " ".join(tokens[:4]).title()[:60]


def _place_from_filename(name: str, owner: str = "", owner_names: list[str] | None = None) -> str:
    stem = Path(name).stem
    names = " ".join([owner or "", *(owner_names or [])])
    owner_tokens = {t.lower() for t in re.split(r"[^A-Za-z]+", names) if t}
    # camel case names like "AmritsarTrip" keep a capitalised word
    camel = [t for t in CAMEL_RE.findall(stem)
             if t.lower() not in GENERIC_TOKENS and t.lower() not in owner_tokens and len(t) > 2]
    if camel:
        return " ".join(camel[:3]).title()
    tokens = [t for t in re.split(r"[_\-. ]+", stem)
              if t and t.isalpha() and t.lower() not in GENERIC_TOKENS
              and t.lower() not in TRIP_WORDS and t.lower() not in EVENT_WORDS
              and t.lower() not in owner_tokens and len(t) > 2]
    if not tokens:
        return ""
    return " ".join(tokens[:3]).title()[:50]


def route_to_destination(cfg, route: FamilyRoute, filename: str) -> Path:
    return cfg.vault.joinpath(*route.path_parts, safe_folder(filename))
