"""Document Intelligence: Auto-detection of document types, entities, and people.

Reads text from files (PDF, DOCX, TXT, OCR scans) and identifies:
1. Document Subtype: Resume, Biometrics (Aadhaar, PAN, Passport, Driving License),
   Education (Degree, Marksheet, Certificate), Health (Prescription, Lab Report, Medical),
   Salary (Payslip, Offer Letter, Form 16), Taxes, Banking, Legal, etc.
2. Belonging Person / Entity: Auto-extracts person name from resume headers,
   government ID records, patient names, employee names, student names, or kinship
   (Kush, Father, Mother, Papa, Mummy, Bua, etc.).
"""
from __future__ import annotations

import getpass
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DocEntityInfo:
    person: str = ""
    doc_type: str = ""  # Resume | Biometrics | Education | Health | Salary | Taxes | Banking | Legal | Custom
    subtype: str = ""   # e.g. Aadhaar, PAN, Passport, Marksheet, Prescription, Payslip
    confidence: float = 0.0
    details: dict = field(default_factory=dict)
    reason: str = ""
    topic: str = ""
    subtopic: str = ""
    project: str = ""
    company: str = ""
    domain: str = ""
    context_path: list[str] = field(default_factory=list)


@dataclass
class ContextTopicInfo:
    topic: str = ""
    subtopic: str = ""
    project: str = ""
    company: str = ""
    domain: str = ""
    confidence: float = 0.0
    context_path: list[str] = field(default_factory=list)
    reason: str = ""


# Stopwords that should never be treated as person names
PERSON_STOPWORDS = {
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
    'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec', 'update', 'draft', 'version',
    'introduction', 'intro', 'algorithms', 'desktop', 'installer', 'setup',
    'free', 'docker', 'system', 'windows', 'electricity', 'water', 'gas',
    'wifi', 'broadband', 'rent', 'maintenance', 'utility', 'general',
    'india', 'government', 'unique', 'identification', 'authority', 'income',
    'department', 'permanent', 'account', 'number', 'republic', 'date', 'birth',
    'male', 'female', 'signature', 'holder', 'address', 'examination', 'board',
    'university', 'school', 'college', 'hospital', 'clinic', 'center', 'centre',
    'patient', 'doctor', 'employee', 'employer', 'company', 'corporation', 'limited',
    'pvt', 'ltd', 'private', 'services', 'technologies', 'solutions', 'summary',
    'experience', 'education', 'skills', 'projects', 'objective', 'curriculum',
    'vitae', 'contact', 'email', 'phone', 'address', 'profile', 'professional',
    'roll', 'number', 'marks', 'obtained', 'grade', 'cgpa', 'division', 'passed',
    'semester', 'subject', 'total', 'result', 'status', 'prescription', 'diagnosis',
    'treatment', 'tablet', 'syrup', 'capsule', 'dosage', 'daily', 'morning', 'night',
    'earnings', 'deductions', 'basic', 'hra', 'allowance', 'gross', 'net', 'payable',
    'blood', 'test', 'sample', 'pathology', 'radiology', 'ultrasound', 'xray',
    'checkup', 'health', 'fitness', 'specimen', 'cbc', 'lipid', 'sugar', 'glucose',
    'sheet', 'records', 'details', 'entry', 'order', 'status', 'view', 'preview',
    'national', 'central', 'state', 'council', 'institute', 'provincial', 'govt',
    'software', 'engineer', 'developer', 'programmer', 'architect', 'consultant',
    'analyst', 'manager', 'lead', 'specialist', 'designer', 'administrator',
    'officer', 'executive', 'assistant', 'associate', 'intern', 'trainee',
    'fresher', 'student', 'candidate', 'applicant', 'founder', 'director',
    'president', 'senior', 'junior', 'principal', 'staff', 'member',
    '10th', '12th', '1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th', '9th',
    'first', 'second', 'third', 'fourth', 'fifth', 'tenth', 'twelfth', 'annual',
    'academic', 'secondary', 'higher', 'session', 'term', 'course', 'class',
    'house', 'flat', 'plot', 'street', 'road', 'lane', 'nagar', 'colony', 'sector',
    'block', 'enclave', 'vihar', 'marg', 'bazaar', 'market', 'village', 'post',
    'office', 'dist', 'district', 'city', 'town', 'tehsil', 'pin', 'code', 'near',
    'behind', 'opposite', 'floor', 'building', 'apartment', 'tower', 'phase',
    'delhi', 'mumbai', 'bangalore', 'bengaluru', 'hyderabad', 'kolkata', 'chennai',
    'pune', 'noida', 'gurgaon', 'gurugram',
    'nasa', 'apollo', 'artemis', 'jwst', 'hubble', 'cinri', 'curiosity', 'perseverance', 'mars', 'rover'
}

KINSHIP_MAP = {
    'papa': 'Father',
    'dad': 'Father',
    'father': 'Father',
    'pitaji': 'Father',
    'mummy': 'Mother',
    'mom': 'Mother',
    'mother': 'Mother',
    'mataji': 'Mother',
    'bua': 'Bua',
    'buaji': 'Bua',
    'chacha': 'Chacha',
    'chachi': 'Chachi',
    'mama': 'Mama',
    'mami': 'Mami',
    'bhai': 'Brother',
    'bhaiya': 'Brother',
    'brother': 'Brother',
    'didi': 'Sister',
    'sister': 'Sister',
    'dada': 'Grandfather',
    'dadi': 'Grandmother',
    'nanu': 'Grandfather',
    'nani': 'Grandmother',
}

# Regex patterns
RE_PAN = re.compile(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b")
RE_AADHAAR = re.compile(r"\b(\d{4}\s\d{4}\s\d{4})\b")
RE_PASSPORT = re.compile(r"\b([A-PR-WYa-pr-wy][1-9]\d\s?\d{4}[1-9])\b")
RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
RE_PHONE = re.compile(r"(?:\+?91[\-\s]?)?[6-9]\d{9}\b")


def get_default_primary_user() -> str:
    """Detect current system user name as default person (e.g. 'kushk' -> 'Kush')."""
    try:
        user = getpass.getuser()
        clean = re.sub(r"[^a-zA-Z]", "", user).capitalize()
        # Common pattern: username 'kushk' -> 'Kush'
        if clean.lower().endswith("k") and len(clean) > 3 and clean.lower() != "frank":
            clean = clean[:-1]
        if 2 <= len(clean) <= 15 and clean.lower() not in PERSON_STOPWORDS:
            return clean.capitalize()
    except Exception:
        pass
    return "User"


def normalize_person_name(name: str, configured_people: list[str] | None = None) -> str:
    """Normalize a candidate person name against configured people and kinship terms."""
    if not name:
        return ""
    clean = re.sub(r"[^a-zA-Z\s]", "", name).strip()
    if not clean:
        return ""
    words = clean.split()
    low_full = clean.lower()

    # Check configured people (case-insensitive)
    if configured_people:
        for p in configured_people:
            p_strip = p.strip()
            if not p_strip:
                continue
            if p_strip.lower() == low_full or any(w.lower() == p_strip.lower() for w in words):
                return p_strip.capitalize()

    # Check kinship mapping
    for k, v in KINSHIP_MAP.items():
        if k in words or k == low_full:
            # If user has 'Papa' instead of 'Father' in configured people, honor user's preference
            if configured_people:
                for cp in configured_people:
                    if cp.lower() == k:
                        return cp.capitalize()
            return v

    # Filter out stopwords
    filtered_words = [w for w in words if w.lower() not in PERSON_STOPWORDS and len(w) >= 2]
    if not filtered_words:
        return ""

    # Return capitalized First Name or First + Last Name (max 2 words)
    return " ".join(w.capitalize() for w in filtered_words[:2])


def extract_person_from_resume_header(text: str, configured_people: list[str] | None = None) -> str:
    """Extract candidate name from the top header lines of a resume.

    Resumes almost universally place the candidate's name on the very first 1-3 lines,
    before the contact info (email/phone/address/links).
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    
    # 1. First priority: Check if any configured person name appears in the top lines
    if configured_people:
        for line in lines[:8]:
            for p in configured_people:
                p_clean = p.strip()
                if not p_clean:
                    continue
                pat = r"(?<![a-z0-9])" + re.escape(p_clean.lower()) + r"(?![a-z0-9])"
                if re.search(pat, line.lower()):
                    return p_clean.capitalize()

    # 2. Extract from candidate header line
    job_title_words = {
        'software', 'engineer', 'developer', 'programmer', 'architect', 'consultant',
        'analyst', 'manager', 'lead', 'specialist', 'designer', 'administrator',
        'scientist', 'intern', 'trainee', 'fresher', 'student', 'freelancer',
        'director', 'executive', 'officer', 'assistant', 'associate', 'senior',
        'junior', 'principal', 'head', 'vp', 'fullstack', 'frontend', 'backend',
        'devops', 'machine', 'learning', 'ai', 'data', 'web', 'android', 'ios'
    }
    for line in lines[:6]:
        low = line.lower()
        # Skip generic headings or job titles
        if any(h in low for h in (
            'curriculum vitae', 'resume', 'cv', 'biodata', 'profile', 'portfolio',
            'contact', 'page 1', 'personal details', 'summary', 'about me', 'career'
        )):
            continue
        # If line consists mainly of job title words, skip
        words = line.split()
        if any(w.lower() in job_title_words for w in words):
            continue
        # If line contains email or phone or website, skip
        if RE_EMAIL.search(line) or RE_PHONE.search(line) or 'http' in low or 'github' in low or 'linkedin' in low:
            continue
        # Check if line looks like a person name (1 to 4 capitalized words)
        if 1 <= len(words) <= 4:
            clean_words = [re.sub(r"[^a-zA-Z]", "", w) for w in words]
            clean_words = [w for w in clean_words if w and w.lower() not in PERSON_STOPWORDS]
            if clean_words and all(len(w) >= 2 for w in clean_words):
                return " ".join(w.capitalize() for w in clean_words[:2])
    return ""


FOLDER_NAME_STOPWORDS = {
    'users', 'user', 'windows', 'system', 'appdata', 'program', 'programdata',
    'temp', 'tmp', 'downloads', 'desktop', 'documents', 'pictures', 'videos',
    'music', 'onedrive', 'organized', 'project', 'projects', 'repos', 'repo',
    'whatsapp', 'whatsappimages', 'images', 'photos', 'camera', 'dcim', 'scans',
    'screenshot', 'screenshots', 'gallery', 'media', 'shared', 'incoming',
    'vault', 'storage', 'backup', 'files', 'new folder', 'folder'
}


def extract_person_from_aadhaar(text: str, configured_people: list[str] | None = None) -> tuple[str, str]:
    """Extract cardholder name and relative/father name from Aadhaar OCR text."""
    holder_name = ""
    relative_name = ""

    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # 1. Check if any configured person name appears in the document
    if configured_people:
        for line in lines:
            if any(h in line.lower() for h in ('government', 'india', 'authority', 'uidai', 'enrollment', 'help@', 'mera aadhaar')):
                continue
            for p in configured_people:
                p_clean = p.strip()
                if not p_clean:
                    continue
                pat = r"(?<![a-z0-9])" + re.escape(p_clean.lower()) + r"(?![a-z0-9])"
                if re.search(pat, line.lower()):
                    if not holder_name:
                        holder_name = p_clean.capitalize()
                    elif holder_name.lower() != p_clean.lower() and not relative_name:
                        relative_name = p_clean.capitalize()

    for i, line in enumerate(lines):
        # Name line often precedes DOB or Date of Birth
        if re.search(r"\b(?:DOB|Date of Birth|Year of Birth)\b", line, re.IGNORECASE):
            # Look at previous 1-2 lines for holder name
            for j in range(max(0, i - 2), i):
                prev = lines[j]
                if any(x in prev.lower() for x in ('government', 'india', 'authority', 'uidai', 'enrollment', 'to')):
                    continue
                cand = re.sub(r"[^a-zA-Z\s]", "", prev).strip()
                words = cand.split()
                if 1 <= len(words) <= 4 and all(w.lower() not in PERSON_STOPWORDS for w in words):
                    holder_name = cand
                    break

        # Check for Care of / Son of / Daughter of / Father's Name
        # Stop at commas or address terms
        m_rel = re.search(
            r"(?:C/O|S/O|D/O|W/O|Father|Husband)\s*[:\-]?\s*([A-Za-z\s]+?)(?:,|\bHouse\b|\bRoad\b|\bStreet\b|\bVillage\b|\bDist\b|\bDistrict\b|\bState\b|\bPin\b|\bNear\b|\d|$)",
            line, re.IGNORECASE
        )
        if m_rel:
            cand = re.sub(r"[^a-zA-Z\s]", "", m_rel.group(1)).strip()
            words = [w for w in cand.split() if w.lower() not in PERSON_STOPWORDS]
            if 1 <= len(words) <= 3:
                relative_name = " ".join(words)

        # Check for explicit 'To: [Name]' or 'To\n[Name]'
        m_to = re.search(r"^To\s*[:\-]?\s*([A-Za-z\s]+)", line, re.IGNORECASE)
        if m_to and not holder_name:
            cand = re.sub(r"[^a-zA-Z\s]", "", m_to.group(1)).strip()
            words = cand.split()
            if 1 <= len(words) <= 3 and all(w.lower() not in PERSON_STOPWORDS for w in words):
                holder_name = cand
        elif line.strip().lower() == "to" and i + 1 < len(lines) and not holder_name:
            cand = re.sub(r"[^a-zA-Z\s]", "", lines[i + 1]).strip()
            words = cand.split()
            if 1 <= len(words) <= 3 and all(w.lower() not in PERSON_STOPWORDS for w in words):
                holder_name = cand

    # Fallback: line between government header and 12-digit number
    if not holder_name:
        for line in lines:
            low = line.lower()
            if any(h in low for h in ('government', 'india', 'authority', 'uidai', 'enrollment', 'help@', 'mera aadhaar')):
                continue
            if re.search(r"\d{4}", line):
                continue
            cand = re.sub(r"[^a-zA-Z\s]", "", line).strip()
            words = cand.split()
            if 1 <= len(words) <= 3 and all(w.lower() not in PERSON_STOPWORDS for w in words):
                holder_name = cand
                break

    return holder_name, relative_name


def extract_person_from_pan(text: str) -> tuple[str, str]:
    """Extract cardholder name and father's name from PAN card OCR text."""
    holder_name = ""
    father_name = ""

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        # Look for "Father" / "Father's Name"
        if re.search(r"father(?:\x27s)?(?:\s*name)?\s*[:\-]?", line, re.IGNORECASE):
            same_line = re.sub(r".*father(?:\x27s)?(?:\s*name)?\s*[:\-]?\s*", "", line, flags=re.IGNORECASE).strip()
            cand = re.sub(r"[^a-zA-Z\s]", "", same_line).strip()
            if cand and len(cand.split()) <= 3 and all(w.lower() not in PERSON_STOPWORDS for w in cand.split()):
                father_name = cand
            elif i + 1 < len(lines):
                next_line = re.sub(r"[^a-zA-Z\s]", "", lines[i + 1]).strip()
                if next_line and len(next_line.split()) <= 3 and all(w.lower() not in PERSON_STOPWORDS for w in next_line.split()):
                    father_name = next_line

            # Holder name is typically the line before "Father"
            if not holder_name and i > 0:
                for k in range(i - 1, -1, -1):
                    prev = lines[k]
                    if any(x in prev.lower() for x in ('income', 'tax', 'department', 'govt', 'india', 'permanent')):
                        continue
                    cand = re.sub(r"[^a-zA-Z\s]", "", prev).strip()
                    words = cand.split()
                    if 1 <= len(words) <= 3 and all(w.lower() not in PERSON_STOPWORDS for w in words):
                        holder_name = cand
                        break

        # Also check for 'Name: [Holder Name]'
        m_name = re.search(r"^(?:Name|Holder Name)\s*[:\-]\s*([A-Za-z\s]+)", line, re.IGNORECASE)
        if m_name and not holder_name:
            cand = re.sub(r"[^a-zA-Z\s]", "", m_name.group(1)).strip()
            words = cand.split()
            if 1 <= len(words) <= 3 and all(w.lower() not in PERSON_STOPWORDS for w in words):
                holder_name = cand

    return holder_name, father_name


def extract_person_from_medical(text: str) -> str:
    """Extract patient name from prescription or medical lab report."""
    patterns = [
        r"(?:Patient Name|Patient|Pt\. Name|Name of Patient)\s*[:\-]\s*([A-Za-z\s]+)",
        r"(?:Mr\.|Mrs\.|Ms\.|Master)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        r"(?:Patient Details|Name)\s*[:\-]\s*([A-Za-z\s]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            cand = re.sub(r"[^a-zA-Z\s]", "", m.group(1)).strip()
            words = cand.split()
            clean_words = [w for w in words if w.lower() not in PERSON_STOPWORDS]
            if 1 <= len(clean_words) <= 3:
                return " ".join(clean_words)
    return ""


def extract_person_from_salary(text: str) -> str:
    """Extract employee name from salary slip / payslip."""
    patterns = [
        r"(?:Employee Name|Emp Name|Name of Employee|Staff Name)\s*[:\-]\s*([A-Za-z\s]+)",
        r"(?:Employee|Associate Name)\s*[:\-]\s*([A-Za-z\s]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            cand = re.sub(r"[^a-zA-Z\s]", "", m.group(1)).strip()
            words = cand.split()
            clean_words = [w for w in words if w.lower() not in PERSON_STOPWORDS]
            if 1 <= len(clean_words) <= 3:
                return " ".join(clean_words)
    return ""


def extract_person_from_education(text: str) -> str:
    """Extract student name from marksheet or certificate."""
    patterns = [
        r"(?:Candidate(?:'s)? Name|Student Name|Name of Student|Name of Candidate)\s*[:\-]\s*([A-Za-z\s]+)",
        r"(?:certify that|certified that)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})",
        r"(?:Roll No\b[^\n]*\bName\b\s*[:\-])\s*([A-Za-z\s]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            cand = re.sub(r"[^a-zA-Z\s]", "", m.group(1)).strip()
            words = cand.split()
            clean_words = [w for w in words if w.lower() not in PERSON_STOPWORDS]
            if 1 <= len(clean_words) <= 3:
                return " ".join(clean_words)
    return ""


PERSONAL_DOC_MARKERS = {
    'resume', 'cv', 'biodata', 'passport', 'salary', 'payslip', 'slip', 'marksheet',
    'degree', 'diploma', 'transcript', 'prescription', 'patient', 'medical', 'lab',
    'aadhaar', 'aadhar', 'pan', 'pancard', 'tax', 'itr', 'form16', 'voter', 'license',
    'licence', 'dl', 'bill', 'receipt', 'statement', 'cheque', 'check', 'certificate',
    'cert', 'offer', 'appraisal', 'relieving', 'joining', 'id_card', 'identity',
    'marks', 'grade', '10th', '12th'
}


def is_personal_doc_candidate(filename: str, rel_dir: str = "", text: str = "") -> bool:
    """Check whether filename or context indicates a personal identity or life document."""
    low = f"{filename} {rel_dir} {text[:500]}".lower()
    return any(m in low for m in PERSONAL_DOC_MARKERS)


def detect_person_from_filename_or_path(
    filename: str,
    rel_dir: str = "",
    people: list[str] | None = None,
) -> tuple[str, float, bool]:
    """Detect person name from filename or parent folder provenance.

    Returns (person_name, confidence, is_high_priority).
    is_high_priority is True for configured people and kinship terms.
    """
    stem = Path(filename).stem
    fn_low = filename.lower()
    rel_low = rel_dir.lower()

    # 1. Configured people list (highest priority)
    if people:
        for p in people:
            p_clean = p.strip()
            if not p_clean:
                continue
            pat = r"(?<![a-z0-9])" + re.escape(p_clean.lower()) + r"(?![a-z0-9])"
            if re.search(pat, fn_low):
                return p_clean.capitalize(), 0.95, True
            if rel_low and re.search(pat, rel_low):
                return p_clean.capitalize(), 0.85, True

    # 2. Kinship names (highest priority)
    for k, canonical in KINSHIP_MAP.items():
        pat = r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])"
        if re.search(pat, fn_low):
            if people:
                for cp in people:
                    if cp.lower() == k:
                        return cp.capitalize(), 0.95, True
            return canonical, 0.92, True
        if rel_low and re.search(pat, rel_low):
            return canonical, 0.82, True

    # 3. Filename proper nouns ONLY for personal documents (e.g. 'Kush_Resume.pdf', 'Ramesh_Salary_Slip.pdf')
    # Non-personal documents (engineering, space missions, API specs, science) MUST NOT hallucinate names
    if is_personal_doc_candidate(filename, rel_dir):
        tokens = re.split(r"[^a-zA-Z0-9]+", stem)
        candidates = []
        for t in tokens:
            if not t or any(c.isdigit() for c in t):
                continue
            if not re.match(r"^[a-zA-Z]+$", t):
                continue
            t_low = t.lower()
            if t_low in PERSON_STOPWORDS or len(t) < 3 or len(t) > 20:
                continue
            candidates.append(t.capitalize())

        if candidates:
            return candidates[0], 0.60, False

        # 4. Folder provenance for personal documents (e.g. 'Downloads/Kush/resume.pdf')
        parts = re.split(r"[\\/]", rel_dir)
        for part in reversed(parts):
            cleaned = re.sub(r"[^a-zA-Z]", "", part).strip()
            if cleaned.lower() not in PERSON_STOPWORDS and 2 <= len(cleaned) <= 20:
                if cleaned.lower() not in FOLDER_NAME_STOPWORDS:
                    return cleaned.capitalize(), 0.55, False

    return "", 0.0, False


def _format_folder_name(name: str) -> str:
    """Format name into clean title-cased folder name with underscores or preserved casing."""
    clean = re.sub(r"[<>:\"/\\|?*]", "", name).strip(" ._-")
    if not clean:
        return ""
    parts = re.split(r"[\s_]+", clean)
    clean_parts = []
    for p in parts:
        if not p:
            continue
        if p.isupper() or any(c.isdigit() for c in p):
            clean_parts.append(p)
        else:
            clean_parts.append(p.capitalize())
    return "_".join(clean_parts)


# Space agencies and organizations
SPACE_AGENCIES = {
    "nasa": ("NASA", "Space Exploration"),
    "esa": ("ESA", "Space Exploration"),
    "isro": ("ISRO", "Space Exploration"),
    "spacex": ("SpaceX", "Commercial Spaceflight"),
    "jaxa": ("JAXA", "Space Exploration"),
    "csa": ("CSA", "Space Exploration"),
    "roscosmos": ("Roscosmos", "Space Exploration"),
    "blue_origin": ("Blue_Origin", "Commercial Spaceflight"),
}

SPACE_AGENCY_LONG_NAMES = {
    "national aeronautics and space administration": "NASA",
    "european space agency": "ESA",
    "indian space research organisation": "ISRO",
    "indian space research organization": "ISRO",
    "japan aerospace exploration agency": "JAXA",
    "canadian space agency": "CSA",
}

NASA_CENTERS = (
    "goddard space flight", "jet propulsion laboratory", "kennedy space center",
    "johnson space center", "marshall space flight", "ames research center",
    "langley research center", "glenn research center", "armstrong flight research"
)

SPACE_MISSION_MAP = {
    "jwst": "James_Webb_Space_Telescope",
    "james webb": "James_Webb_Space_Telescope",
    "webb space telescope": "James_Webb_Space_Telescope",
    "hubble": "Hubble_Space_Telescope",
    "curiosity": "Mars_Rover",
    "perseverance": "Mars_Rover",
    "mars rover": "Mars_Rover",
    "mars_rover": "Mars_Rover",
    "ingenuity": "Mars_Rover",
    "opportunity": "Mars_Rover",
    "spirit rover": "Mars_Rover",
    "international space station": "International_Space_Station",
    "iss space": "International_Space_Station",
    "voyager": "Voyager",
    "cassini": "Cassini",
    "europa clipper": "Europa_Clipper",
    "europa_clipper": "Europa_Clipper",
    "nancy grace roman": "Nancy_Grace_Roman_Space_Telescope",
    "roman space telescope": "Nancy_Grace_Roman_Space_Telescope",
    "dragonfly": "Dragonfly",
    "insight": "InSight_Lander",
    "juno": "Juno",
    "new horizons": "New_Horizons",
    "parker solar probe": "Parker_Solar_Probe",
    "spitzer": "Spitzer",
    "chandra": "Chandra",
    "kepler": "Kepler",
    "rosetta": "Rosetta",
    "chandrayaan": "Chandrayaan",
    "starship": "Starship",
    "falcon 9": "Falcon_9",
    "falcon_9": "Falcon_9",
    "hayabusa": "Hayabusa",
}

SPACE_TRAILING_DOC_WORDS = {
    "report", "survey", "design", "telemetry", "specification", "spec",
    "simulation", "overview", "plan", "doc", "paper", "data", "notes",
    "calibration", "log", "logs", "guide", "manual", "analysis"
}

# Comprehensive academic & scientific disciplines
ACADEMIC_DISCIPLINES = [
    # Physics & Astronomy
    ("quantum mechanics", "Quantum_Mechanics", "Physics"),
    ("quantum computing", "Quantum_Computing", "Physics"),
    ("astrophysics", "Astrophysics", "Physics"),
    ("thermodynamics", "Thermodynamics", "Physics"),
    ("electromagnetism", "Electromagnetism", "Physics"),
    ("particle physics", "Particle_Physics", "Physics"),
    ("relativity", "General_Relativity", "Physics"),
    # Chemistry
    ("organic chemistry", "Organic_Chemistry", "Chemistry"),
    ("inorganic chemistry", "Inorganic_Chemistry", "Chemistry"),
    ("physical chemistry", "Physical_Chemistry", "Chemistry"),
    ("biochemistry", "Biochemistry", "Chemistry"),
    ("analytical chemistry", "Analytical_Chemistry", "Chemistry"),
    # Biology & Medicine
    ("molecular biology", "Molecular_Biology", "Biology"),
    ("genetics", "Genetics", "Biology"),
    ("immunology", "Immunology", "Biology"),
    ("neuroscience", "Neuroscience", "Biology"),
    ("bioinformatics", "Bioinformatics", "Biology"),
    ("microbiology", "Microbiology", "Biology"),
    ("cellular biology", "Cell_Biology", "Biology"),
    ("cell biology", "Cell_Biology", "Biology"),
    # Mathematics
    ("linear algebra", "Linear_Algebra", "Mathematics"),
    ("differential equations", "Differential_Equations", "Mathematics"),
    ("calculus", "Calculus", "Mathematics"),
    ("abstract algebra", "Abstract_Algebra", "Mathematics"),
    ("topology", "Topology", "Mathematics"),
    ("probability and statistics", "Probability_And_Statistics", "Mathematics"),
    # Computer Science & Engineering
    ("machine learning", "Machine_Learning", "Artificial Intelligence"),
    ("deep learning", "Deep_Learning", "Artificial Intelligence"),
    ("computer vision", "Computer_Vision", "Artificial Intelligence"),
    ("natural language processing", "Natural_Language_Processing", "Artificial Intelligence"),
    ("operating systems", "Operating_Systems", "Computer Science"),
    ("database systems", "Database_Systems", "Computer Science"),
    ("distributed systems", "Distributed_Systems", "Computer Science"),
    ("computer networks", "Computer_Networks", "Computer Science"),
    ("cryptography", "Cryptography", "Computer Science"),
    # Economics & Business
    ("microeconomics", "Microeconomics", "Economics"),
    ("macroeconomics", "Macroeconomics", "Economics"),
    ("corporate finance", "Corporate_Finance", "Economics"),
    ("financial accounting", "Financial_Accounting", "Economics"),
]


def extract_contextual_topic(
    filename: str,
    text: str = "",
    rel_dir: str = "",
    people: list[str] | None = None,
) -> ContextTopicInfo:
    """Dynamically extract topic, subject, project, company, entity, or domain on the spot.

    Supports:
    - Dynamic open-domain topic discovery without rigid predefined taxonomy categories
    - Explicit filename marker prefixes: Project_, Subject_, Topic_, Company_, Domain_, Entity_
    - Space agencies and missions: NASA, ESA, ISRO, SpaceX, JAXA, Roscosmos, etc. (JWST, Apollo, Artemis, Mars Rover, Roman Telescope, Rosetta, Chandrayaan, Starship)
    - Office work and enterprise topics with dynamic subtopic extraction (e.g. Father/Office_Work/Vendor_Invoices_Q3, Employee_Payroll_Q4, Board_Meeting_Minutes)
    - Specific projects, APIs, systems, and platforms (e.g. Cinri Health API, Stripe Payment API, Tesla Autopilot)
    - Academic subjects and scientific disciplines (Machine Learning Transformers, Organic Chemistry, Quantum Computing, Immunology, etc.)
    - Structured delimited filenames ("Title - Subtopic - ...")
    - Key-value metadata extraction from document headers (Project:, Subject:, Topic:, Organization:, Company:, Domain:)
    """
    info = ContextTopicInfo()
    fn_stem = Path(filename).stem
    fn_low = filename.lower()
    text_sample = (text or "")[:15000]
    text_low = text_sample.lower()
    rel_low = (rel_dir or "").lower()
    combined_low = f"{fn_low} {rel_low} {text_low}"

    # -----------------------------------------------------------------
    # 1. EXPLICIT MARKER PREFIXES IN FILENAME (e.g. Project_*, Subject_*, Company_*, Domain_*)
    # -----------------------------------------------------------------
    m_pfx = re.match(
        r"^(?:(Project|Subject|Topic|Company|Domain|Entity))[_\s-]+(.+)$",
        fn_stem,
        re.IGNORECASE
    )
    if m_pfx:
        marker_kind = m_pfx.group(1).capitalize()
        remainder = m_pfx.group(2).strip(" ._-")
        if " - " in remainder or " -- " in remainder:
            parts = re.split(r"\s+[-–—]+\s+", remainder)
            topic = _format_folder_name(parts[0])
            subtopic = _format_folder_name(parts[1]) if len(parts) > 1 else ""
        else:
            tokens = [t for t in re.split(r"[\s_]+", remainder) if t]
            if marker_kind in ("Subject", "Domain", "Topic"):
                if len(tokens) == 1:
                    topic = _format_folder_name(tokens[0])
                    subtopic = ""
                else:
                    topic = _format_folder_name(tokens[0])
                    subtopic = _format_folder_name("_".join(tokens[1:]))
            else:
                if len(tokens) == 1:
                    topic = _format_folder_name(tokens[0])
                    subtopic = ""
                elif len(tokens) == 2:
                    topic = _format_folder_name(tokens[0])
                    subtopic = _format_folder_name(tokens[1])
                elif len(tokens) == 3:
                    topic = _format_folder_name("_".join(tokens[:2]))
                    subtopic = _format_folder_name(tokens[2])
                else:
                    topic = _format_folder_name("_".join(tokens[:2]))
                    subtopic = _format_folder_name("_".join(tokens[2:]))

        if topic and len(topic) >= 2 and topic.lower() not in PERSON_STOPWORDS:
            info.topic = topic
            info.subtopic = subtopic
            info.context_path = [topic, subtopic] if subtopic else [topic]
            info.confidence = 0.95
            info.reason = f"Dynamic {marker_kind.lower()} folder creation: {'/'.join(info.context_path)}"
            if marker_kind == "Project":
                info.project = topic
            elif marker_kind == "Company":
                info.company = topic
            elif marker_kind in ("Subject", "Domain"):
                info.domain = topic
            return info

    # -----------------------------------------------------------------
    # 2. STRUCTURED DELIMITED FILENAMES ("Title - Subtopic - ...")
    # -----------------------------------------------------------------
    if " - " in fn_stem or " -- " in fn_stem or " – " in fn_stem:
        parts = [p.strip() for p in re.split(r"\s+[-–—]+\s+", fn_stem) if p.strip()]
        if len(parts) >= 2:
            p1 = _format_folder_name(parts[0])
            p2 = _format_folder_name(parts[1])
            is_person_p1 = False
            if people and any(p.lower() == p1.lower() for p in people):
                is_person_p1 = True
            if p1.lower() in KINSHIP_MAP:
                is_person_p1 = True
            if p1 and len(p1) >= 2 and p1.lower() not in PERSON_STOPWORDS and not is_person_p1:
                info.topic = p1
                info.subtopic = p2
                info.context_path = [p1, p2] if p2 else [p1]
                info.confidence = 0.92
                info.reason = f"Dynamic structured filename topic: {p1}/{p2}"
                return info

    # -----------------------------------------------------------------
    # 3. SPACE EXPLORATION & AEROSPACE AGENCIES (NASA, ESA, ISRO, SpaceX, JAXA)
    # -----------------------------------------------------------------
    agency_found = ""
    domain_name = "Space Exploration"

    if (
        bool(re.search(r"(?<![a-z0-9])(?:nasa|apollo|artemis|jwst|hubble|curiosity|perseverance)(?![a-z0-9])", combined_low))
        or any(c in combined_low for c in NASA_CENTERS)
        or "national aeronautics and space administration" in combined_low
    ):
        agency_found = "NASA"
    elif bool(re.search(r"(?<![a-z0-9])esa(?![a-z0-9])", fn_low)) or "european space agency" in combined_low:
        agency_found = "ESA"
    elif bool(re.search(r"(?<![a-z0-9])isro(?![a-z0-9])", fn_low)) or "indian space research" in combined_low:
        agency_found = "ISRO"
    elif "spacex" in combined_low:
        agency_found = "SpaceX"
        domain_name = "Commercial Spaceflight"
    elif bool(re.search(r"(?<![a-z0-9])jaxa(?![a-z0-9])", fn_low)) or "japan aerospace" in combined_low:
        agency_found = "JAXA"

    if agency_found:
        info.topic = agency_found
        info.company = agency_found
        info.domain = domain_name
        sub = ""

        # Check for Apollo missions (Apollo 11, etc.)
        m_apollo = re.search(r"(?<![a-z0-9])apollo(?:[\s_]*(\d+))?(?![a-z0-9])", combined_low)
        # Check for Artemis missions
        m_artemis = re.search(r"(?<![a-z0-9])artemis(?:[\s_]*(\d+))?(?![a-z0-9])", combined_low)
        # Check for Chandrayaan missions
        m_chandra = re.search(r"(?<![a-z0-9])chandrayaan(?:[\s_]*(\d+))?(?![a-z0-9])", combined_low)
        # Check for Voyager missions
        m_voyager = re.search(r"(?<![a-z0-9])voyager(?:[\s_]*([12]))?(?![a-z0-9])", combined_low)

        if m_apollo and (agency_found == "NASA" or "apollo" in combined_low):
            sub = f"Apollo_{m_apollo.group(1)}" if m_apollo.group(1) else "Apollo_11"
        elif m_artemis and (agency_found == "NASA" or "artemis" in combined_low):
            sub = f"Artemis_{m_artemis.group(1)}" if m_artemis.group(1) else "Artemis"
        elif m_chandra and (agency_found == "ISRO" or "chandrayaan" in combined_low):
            sub = f"Chandrayaan_{m_chandra.group(1)}" if m_chandra.group(1) else "Chandrayaan_3"
        elif m_voyager:
            sub = f"Voyager_{m_voyager.group(1)}" if m_voyager.group(1) else "Voyager"
        else:
            # Check known missions map
            for phrase, canon in SPACE_MISSION_MAP.items():
                if phrase in combined_low:
                    sub = canon
                    break

        # Dynamic mission extraction from filename if not in known map
        if not sub:
            # e.g. NASA_Nancy_Grace_Roman_Space_Telescope_Survey.pdf -> Nancy_Grace_Roman_Space_Telescope
            # Strip agency name from start
            fn_tokens = [t for t in re.split(r"[\s_]+", fn_stem) if t]
            if fn_tokens and fn_tokens[0].upper() == agency_found.upper():
                rest = fn_tokens[1:]
                # Remove trailing document kind words
                while rest and rest[-1].lower() in SPACE_TRAILING_DOC_WORDS:
                    rest.pop()
                if rest:
                    sub = _format_folder_name("_".join(rest))

        if not sub:
            for cand in ("optical_design", "optical design", "telemetry", "flight_plan", "flight plan", "navigation", "mission_report", "mission report", "propulsion"):
                if cand in combined_low:
                    sub = _format_folder_name(cand)
                    break

        info.subtopic = sub
        info.context_path = [agency_found, sub] if sub else [agency_found]
        info.confidence = 0.95
        info.reason = f"Dynamic space agency folder creation: {'/'.join(info.context_path)}"
        return info

    # Check for standalone space mission references even if agency acronym not prefixed
    for phrase, canon in (("james webb", "James_Webb_Space_Telescope"), ("jwst", "James_Webb_Space_Telescope"),
                          ("curiosity rover", "Mars_Rover"), ("perseverance rover", "Mars_Rover"),
                          ("hubble telescope", "Hubble_Space_Telescope"), ("europa clipper", "Europa_Clipper"),
                          ("rosetta", "Rosetta"), ("chandrayaan", "Chandrayaan_3")):
        if phrase in combined_low:
            agency = "ESA" if canon == "Rosetta" else ("ISRO" if canon.startswith("Chandrayaan") else "NASA")
            info.topic = agency
            info.subtopic = canon
            info.context_path = [agency, canon]
            info.confidence = 0.95
            info.reason = f"Dynamic contextual folder creation: {agency}/{canon}"
            return info

    # -----------------------------------------------------------------
    # 4. OFFICE WORK & CORPORATE TOPICS (Dynamic Subtopic Extraction)
    # -----------------------------------------------------------------
    has_office_work = any(k in combined_low for k in ("office work", "office_work", "office-work", "office_tasks", "officework"))
    has_vendor_invoices = any(k in combined_low for k in ("vendor invoice", "vendor_invoice", "vendor invoices", "vendor_invoices", "vendor bill", "vendor payments"))
    has_purchase_orders = any(k in combined_low for k in ("purchase order", "purchase_order", "purchase orders", "purchase_orders"))
    has_q = re.search(r"(?<![a-z0-9])(?:q([1-4])|quarter\s*([1-4]))(?![a-z0-9])", combined_low)
    q_str = f"Q{has_q.group(1) or has_q.group(2)}" if has_q else ""

    if has_office_work or has_vendor_invoices or has_purchase_orders:
        info.topic = "Office_Work"
        info.domain = "Business & Corporate"
        sub = ""

        # Dynamically extract subtopic from filename portion following Office_Work
        # e.g. 'Father_Office_Work_Vendor_Invoices_Q3.xlsx' -> 'Vendor_Invoices_Q3'
        # e.g. 'Father_Office_Work_Employee_Payroll_Q4.xlsx' -> 'Employee_Payroll_Q4'
        # e.g. 'Office_Work_Board_Meeting_Minutes.docx' -> 'Board_Meeting_Minutes'
        fn_tokens = [t for t in re.split(r"[\s_]+", fn_stem) if t]
        # Find index of Office_Work in tokens
        idx_ow = -1
        for i, t in enumerate(fn_tokens):
            if t.lower() in ("office", "officework"):
                if i + 1 < len(fn_tokens) and fn_tokens[i + 1].lower() == "work":
                    idx_ow = i + 1
                    break
                else:
                    idx_ow = i
                    break

        if idx_ow != -1 and idx_ow + 1 < len(fn_tokens):
            sub_tokens = fn_tokens[idx_ow + 1:]
            sub = _format_folder_name("_".join(sub_tokens))

        if not sub:
            if has_vendor_invoices:
                sub = f"Vendor_Invoices_{q_str}" if q_str else "Vendor_Invoices"
            elif has_purchase_orders:
                sub = f"Purchase_Orders_{q_str}" if q_str else "Purchase_Orders"
            elif "client proposal" in combined_low or "proposals" in combined_low:
                sub = "Client_Proposals"
            elif "payroll" in combined_low or "salary" in combined_low:
                sub = f"Employee_Payroll_{q_str}" if q_str else "Employee_Payroll"
            elif "board meeting" in combined_low or "minutes" in combined_low:
                sub = "Board_Meeting_Minutes"
            elif "financial" in combined_low or "quarterly" in combined_low:
                sub = f"Quarterly_Reports_{q_str}" if q_str else "Quarterly_Reports"
            elif q_str:
                sub = f"Quarterly_Work_{q_str}"
            else:
                sub = "General"

        info.subtopic = sub
        info.context_path = ["Office_Work", sub] if sub else ["Office_Work"]
        info.confidence = 0.93
        info.reason = f"Dynamic office topic identified: {'/'.join(info.context_path)}"
        return info

    # -----------------------------------------------------------------
    # 5. EXPLICIT KEY-VALUE METADATA PATTERNS IN TEXT
    # (High priority: Document explicitly declares its Project, Subject, Topic, etc.)
    # -----------------------------------------------------------------
    re_fields = [
        (r"(?:^|\n)[ \t]*Project\s*[:\-][ \t]*([A-Za-z0-9_ \t]{3,50})", "Project"),
        (r"(?:^|\n)[ \t]*Subject\s*[:\-][ \t]*([A-Za-z0-9_ \t]{3,50})", "Subject"),
        (r"(?:^|\n)[ \t]*Topic\s*[:\-][ \t]*([A-Za-z0-9_ \t]{3,50})", "Topic"),
        (r"(?:^|\n)[ \t]*Organization\s*[:\-][ \t]*([A-Za-z0-9_ \t]{3,50})", "Organization"),
        (r"(?:^|\n)[ \t]*Company\s*[:\-][ \t]*([A-Za-z0-9_ \t]{3,50})", "Company"),
        (r"(?:^|\n)[ \t]*Domain\s*[:\-][ \t]*([A-Za-z0-9_ \t]{3,50})", "Domain"),
    ]
    for pat, kind in re_fields:
        m = re.search(pat, text_sample[:2000], re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            formatted = _format_folder_name(val)
            if formatted and len(formatted) >= 3 and formatted.lower() not in PERSON_STOPWORDS:
                info.topic = formatted
                # Check for subtopic in text
                m_sub = re.search(
                    r"(?:^|\n)[ \t]*(?:Subtopic|Module|Chapter|Section)\s*[:\-][ \t]*([A-Za-z0-9_ \t]{3,50})",
                    text_sample[:2500],
                    re.IGNORECASE
                )
                if m_sub:
                    sub_val = _format_folder_name(m_sub.group(1).strip())
                    if sub_val and sub_val.lower() not in PERSON_STOPWORDS:
                        info.subtopic = sub_val

                info.context_path = [formatted, info.subtopic] if info.subtopic else [formatted]
                info.confidence = 0.94
                info.reason = f"Dynamic {kind.lower()} metadata identified: {'/'.join(info.context_path)}"
                if kind == "Project":
                    info.project = formatted
                elif kind in ("Company", "Organization"):
                    info.company = formatted
                return info

    # -----------------------------------------------------------------
    # 6. SPECIFIC PROJECTS & APIS (e.g. Cinri Health API, General APIs, Systems)
    # -----------------------------------------------------------------
    is_cinri = any(k in combined_low for k in ("cinri health api", "cinri_health_api", "cinri health", "cinri_health", "cinri"))
    if is_cinri:
        info.topic = "Cinri_Health_API"
        info.project = "Cinri Health API"
        info.company = "Cinri Health"
        info.domain = "Healthcare Technology"
        sub = ""
        if "endpoint" in combined_low:
            sub = "Endpoints"
        elif "spec" in combined_low or "specification" in combined_low:
            sub = "Specifications"
        elif "architecture" in combined_low:
            sub = "Architecture"
        elif "doc" in combined_low or "guide" in combined_low:
            sub = "Documentation"
        info.subtopic = sub
        info.context_path = ["Cinri_Health_API", sub] if (sub and sub in ("Endpoints", "Architecture")) else ["Cinri_Health_API"]
        info.confidence = 0.94
        info.reason = f"Dynamic project topic identified: {'/'.join(info.context_path)}"
        return info

    # Generalized API / System / Engine / Platform / Architecture project detection:
    # e.g. "Stripe_Payment_API", "Tesla_Autopilot", "Astra_Billing_Engine", "Kafka_Event_Pipeline"
    PROJECT_SYSTEM_KEYWORDS = {'api', 'sdk', 'system', 'platform', 'engine', 'pipeline', 'framework', 'autopilot'}
    fn_tokens = [t for t in re.split(r"[\s_]+", fn_stem) if t]
    for i, t in enumerate(fn_tokens):
        if t.lower() in PROJECT_SYSTEM_KEYWORDS and 0 < i <= 3:
            cand_topic = _format_folder_name("_".join(fn_tokens[:i+1]))
            if cand_topic.lower() not in ("the_api", "rest_api", "json_api", "fastapi", "web_api", "file_system", "operating_system"):
                info.topic = cand_topic
                info.project = cand_topic
                cand_sub = _format_folder_name("_".join(fn_tokens[i+1:]))
                info.subtopic = cand_sub
                info.context_path = [cand_topic, cand_sub] if cand_sub else [cand_topic]
                info.confidence = 0.93
                info.reason = f"Dynamic project identified: {'/'.join(info.context_path)}"
                return info

    m_proj = re.search(
        r"\b([A-Z][a-zA-Z0-9]+(?:[ \t_]+[A-Z][a-zA-Z0-9]+)*[ \t_]+(?:API|SDK|System|Platform|Engine|Pipeline|Architecture|Service|Framework|Autopilot))\b",
        f"{filename}\n{text_sample[:1200]}"
    )
    if m_proj:
        proj_name = _format_folder_name(m_proj.group(1))
        if proj_name.lower() not in ("the_api", "rest_api", "json_api", "fastapi", "web_api", "file_system", "operating_system"):
            info.topic = proj_name
            info.project = proj_name
            sub = ""
            for sub_cand in ("Endpoints", "Specifications", "Architecture", "Documentation", "Integration_Guide", "Design", "Telemetry"):
                if sub_cand.lower() in combined_low and sub_cand.lower() != proj_name.lower():
                    sub = sub_cand
                    break
            info.subtopic = sub
            info.context_path = [proj_name, sub] if sub else [proj_name]
            info.confidence = 0.91
            info.reason = f"Dynamic project identified: {'/'.join(info.context_path)}"
            return info

    # -----------------------------------------------------------------
    # 6. ACADEMIC SUBJECTS & SCIENTIFIC DISCIPLINES
    # -----------------------------------------------------------------
    # Machine Learning & Transformers
    is_ml_transformers = (
        ("machine learning" in combined_low or "machine_learning" in combined_low or "deep learning" in combined_low)
        and ("transformer" in combined_low or "transformers" in combined_low or "attention is all you need" in combined_low or "attention mechanism" in combined_low)
    ) or ("machine_learning_transformers" in combined_low) or ("attention is all you need" in combined_low)

    if is_ml_transformers:
        info.topic = "Machine_Learning_Transformers"
        info.domain = "Artificial Intelligence"
        sub = ""
        if "vision" in combined_low:
            sub = "Vision_Transformers"
        elif "llm" in combined_low or "language model" in combined_low:
            sub = "Language_Models"
        elif "attention" in fn_low:
            sub = "Attention"
        info.subtopic = sub
        info.context_path = ["Machine_Learning_Transformers", sub] if sub else ["Machine_Learning_Transformers"]
        info.confidence = 0.93
        info.reason = f"Dynamic subject identified: {'/'.join(info.context_path)}"
        return info

    # Organic Chemistry
    is_organic_chem = "organic chemistry" in combined_low or "organic_chemistry" in combined_low
    if is_organic_chem:
        info.topic = "Organic_Chemistry"
        info.domain = "Chemistry"
        sub = ""
        if "reaction mechanism" in combined_low or "reaction_mechanism" in combined_low or "reaction" in combined_low:
            sub = "Reaction_Mechanisms"
        elif "hydrocarbon" in combined_low:
            sub = "Hydrocarbons"
        elif "synthesis" in combined_low:
            sub = "Synthesis"
        elif "spectroscopy" in combined_low:
            sub = "Spectroscopy"
        elif "stereochemistry" in combined_low:
            sub = "Stereochemistry"
        info.subtopic = sub
        info.context_path = ["Organic_Chemistry", sub] if sub else ["Organic_Chemistry"]
        info.confidence = 0.93
        info.reason = f"Dynamic subject identified: {'/'.join(info.context_path)}"
        return info

    # Broad Academic & Scientific Disciplines
    for phrase, folder, domain in ACADEMIC_DISCIPLINES:
        if phrase in combined_low or folder.lower() in combined_low:
            info.topic = folder
            info.domain = domain
            sub = ""
            # Dynamically extract subtopic if filename has [Subject]_[Subtopic]
            fn_tokens = [t for t in re.split(r"[\s_]+", fn_stem) if t]
            subj_words = folder.split("_")
            # If start of filename matches subject words
            if len(fn_tokens) > len(subj_words) and all(fn_tokens[i].lower() == subj_words[i].lower() for i in range(len(subj_words))):
                rest_tokens = fn_tokens[len(subj_words):]
                # Filter out generic words like 'notes', 'lecture', 'chapter', 'study', 'pdf', 'doc'
                clean_rest = [w for w in rest_tokens if w.lower() not in ("notes", "lecture", "study", "analysis", "paper", "overview", "doc", "ch", "chapter")]
                if clean_rest:
                    sub = _format_folder_name("_".join(clean_rest))

            info.subtopic = sub
            info.context_path = [folder, sub] if sub else [folder]
            info.confidence = 0.91
            info.reason = f"Dynamic academic subject identified: {'/'.join(info.context_path)}"
            return info


    # -----------------------------------------------------------------
    # 8. MARKDOWN HEADING (# Title)
    # -----------------------------------------------------------------
    m_h1 = re.search(r"(?:^|\n)#\s+([A-Za-z0-9_\s]{4,50})(?:\n|$)", text_sample[:1000])
    if m_h1:
        h1 = m_h1.group(1).strip()
        formatted = _format_folder_name(h1)
        if formatted and formatted.lower() not in PERSON_STOPWORDS and len(formatted.split("_")) >= 2:
            info.topic = formatted
            info.context_path = [formatted]
            info.confidence = 0.82
            info.reason = f"Dynamic document heading identified: {formatted}"
            return info

    return info


def recognize_document(
    filename: str,
    text: str = "",
    rel_dir: str = "",
    people: list[str] | None = None,
) -> DocEntityInfo:
    """Intelligent document recognition: identifies doc type, subtype, and person.

    Supports:
    - Resume
    - Biometrics (Aadhaar, PAN, Passport, Driving License, Voter ID)
    - Education (Marksheet, Degree, Diploma, Academic Certificate)
    - Health (Prescription, Medical Report, Lab Test, Hospital Bill)
    - Salary (Payslip, Offer Letter, Experience Letter, Form 16)
    - Taxes, Banking, Legal
    """
    fn_low = filename.lower()
    text_low = (text or "")[:5000].lower()
    combined_low = f"{fn_low} {text_low}"
    info = DocEntityInfo()

    fn_person, fn_conf, fn_is_priority = detect_person_from_filename_or_path(filename, rel_dir, people)

    # -------------------------------------------------------------
    # 1. BIOMETRICS & GOVERNMENT IDENTITY
    # -------------------------------------------------------------
    has_pan = (
        bool(re.search(r"(?<![a-z0-9])pan(?![a-z0-9])", fn_low))
        or 'pan card' in combined_low or 'pancard' in combined_low
        or bool(RE_PAN.search(text))
        or any(k in combined_low for k in ('permanent account number', 'income tax department'))
    )
    is_aadhaar = any(k in combined_low for k in ('aadhaar', 'aadhar', 'uidai', 'unique identification')) or bool(RE_AADHAAR.search(text))
    is_pan = has_pan
    is_passport = any(k in combined_low for k in ('passport', 'republic of india')) or bool(RE_PASSPORT.search(text))
    is_license = any(k in combined_low for k in ('driving licence', 'driving license', 'transport department')) or bool(re.search(r"(?<![a-z0-9])dl(?![a-z0-9])", fn_low))
    is_voter = any(k in combined_low for k in ('voter id', 'voter card', 'election commission', 'epic no', 'voter'))

    if is_aadhaar or is_pan or is_passport or is_license or is_voter or 'biometric' in combined_low:
        info.doc_type = "Biometrics"
        info.confidence = 0.95

        if is_aadhaar:
            info.subtype = "Aadhaar"
            holder, rel = extract_person_from_aadhaar(text, people)
            norm_holder = normalize_person_name(holder, people)
            norm_rel = normalize_person_name(rel, people)
            if fn_is_priority:
                info.person = fn_person
            elif norm_holder:
                info.person = norm_holder
            elif fn_person:
                info.person = fn_person
            elif norm_rel:
                info.person = norm_rel
            else:
                info.person = people[0] if (people and len(people) == 1) else get_default_primary_user()
            info.reason = "Aadhaar / Biometric identity record identified"
            return info

        if is_pan:
            info.subtype = "PAN"
            holder, father = extract_person_from_pan(text)
            norm_holder = normalize_person_name(holder, people)
            norm_father = normalize_person_name(father, people)
            if fn_person in ("Father", "Papa", "Dad"):
                info.person = fn_person
            elif fn_is_priority:
                info.person = fn_person
            elif norm_holder:
                info.person = norm_holder
            elif fn_person:
                info.person = fn_person
            elif norm_father:
                info.person = norm_father
            else:
                info.person = people[0] if (people and len(people) == 1) else get_default_primary_user()
            info.reason = "PAN Card identity record identified"
            return info

        if is_passport:
            info.subtype = "Passport"
            info.person = fn_person if fn_is_priority else (normalize_person_name(extract_person_from_resume_header(text, people), people) or fn_person or (people[0] if (people and len(people) == 1) else get_default_primary_user()))
            info.reason = "Passport identity record identified"
            return info

        if is_license:
            info.subtype = "Driving License"
            info.person = fn_person or (people[0] if (people and len(people) == 1) else get_default_primary_user())
            info.reason = "Driving License identified"
            return info

        info.subtype = "Identity ID"
        info.person = fn_person or (people[0] if (people and len(people) == 1) else get_default_primary_user())
        info.reason = "Official identity document identified"
        return info

    # -------------------------------------------------------------
    # 2. RESUME / CV
    # -------------------------------------------------------------
    resume_keywords = ('resume', 'curriculum vitae', 'cv', 'biodata')
    has_resume_kw = any(k in fn_low for k in resume_keywords) or any(k in text_low[:500] for k in resume_keywords)
    has_resume_structure = (
        ('education' in text_low or 'skills' in text_low) and
        ('experience' in text_low or 'projects' in text_low or 'work history' in text_low)
    )

    if has_resume_kw or (has_resume_structure and len(text) > 100):
        info.doc_type = "Resume"
        info.subtype = "CV"
        info.confidence = 0.94
        extracted_name = extract_person_from_resume_header(text, people)
        norm_name = normalize_person_name(extracted_name, people)
        if fn_is_priority:
            info.person = fn_person
        elif norm_name:
            info.person = norm_name
        elif fn_person:
            info.person = fn_person
        else:
            info.person = people[0] if (people and len(people) == 1) else get_default_primary_user()
        info.reason = "Resume / CV detected"
        return info

    # -------------------------------------------------------------
    # 3. SALARY & EMPLOYMENT / JOB
    # -------------------------------------------------------------
    salary_keywords = (
        'salary slip', 'payslip', 'pay slip', 'basic salary', 'gross salary', 'net salary',
        'gross pay', 'net pay', 'earnings and deductions', 'provident fund', 'form 16',
        'form16', 'offer letter', 'appointment letter', 'appraisal letter', 'relieving letter',
        'experience letter', 'salary'
    )
    if any(k in combined_low for k in salary_keywords):
        info.doc_type = "Salary"
        info.confidence = 0.92
        if 'payslip' in combined_low or 'salary' in combined_low or 'pay slip' in combined_low:
            info.subtype = "Payslip"
        elif 'offer' in combined_low:
            info.subtype = "Offer Letter"
        elif 'form 16' in combined_low or 'form16' in combined_low:
            info.subtype = "Form 16"
        else:
            info.subtype = "Employment"

        emp_name = extract_person_from_salary(text)
        norm_emp = normalize_person_name(emp_name, people)
        if fn_is_priority:
            info.person = fn_person
        elif norm_emp:
            info.person = norm_emp
        elif fn_person:
            info.person = fn_person
        else:
            info.person = people[0] if (people and len(people) == 1) else get_default_primary_user()
        info.reason = "Salary slip or employment document identified"
        return info

    # -------------------------------------------------------------
    # 4. EDUCATION & ACADEMICS
    # -------------------------------------------------------------
    education_keywords = (
        'marksheet', 'mark sheet', 'degree', 'diploma', 'transcript', 'board of secondary',
        'cbse', 'icse', 'university', 'bachelor', 'master', 'b.tech', 'btech', 'b.sc',
        'b.com', 'm.tech', 'provisional certificate', 'passing certificate', 'grade card',
        'semester examination', 'roll no', 'certificate', '10th', '12th', 'graduation',
        'academic', 'school leaving', 'migration certificate'
    )
    if any(k in combined_low for k in education_keywords) and not ('salary' in combined_low or 'invoice' in combined_low):
        info.doc_type = "Education"
        info.confidence = 0.90
        if 'marksheet' in combined_low or 'mark sheet' in combined_low or '10th' in combined_low or '12th' in combined_low or 'grade card' in combined_low:
            info.subtype = "Marksheet"
        elif 'degree' in combined_low or 'bachelor' in combined_low or 'master' in combined_low or 'btech' in combined_low:
            info.subtype = "Degree"
        elif 'diploma' in combined_low:
            info.subtype = "Diploma"
        elif 'transcript' in combined_low:
            info.subtype = "Transcript"
        else:
            info.subtype = "Certificate"

        student_name = extract_person_from_education(text)
        norm_student = normalize_person_name(student_name, people)
        if fn_is_priority:
            info.person = fn_person
        elif norm_student:
            info.person = norm_student
        elif fn_person:
            info.person = fn_person
        else:
            info.person = people[0] if (people and len(people) == 1) else get_default_primary_user()
        info.reason = "Educational degree or marksheet identified"
        return info

    # -------------------------------------------------------------
    # 5. HEALTH & MEDICAL
    # -------------------------------------------------------------
    health_keywords = (
        'prescription', 'dr.', 'doctor', 'hospital', 'clinic', 'diagnosis', 'rx',
        'lab report', 'blood test', 'pathology', 'radiology', 'ultrasound', 'x-ray',
        'mri scan', 'ct scan', 'discharge summary', 'patient name', 'mediclaim',
        'hemoglobin', 'lipid profile', 'medical prescription'
    )
    if any(k in combined_low for k in health_keywords) and not ('salary' in combined_low):
        info.doc_type = "Health"
        info.confidence = 0.90
        if 'prescription' in combined_low:
            info.subtype = "Prescription"
        elif 'lab' in combined_low or 'test' in combined_low or 'blood' in combined_low:
            info.subtype = "Lab Report"
        elif 'discharge' in combined_low:
            info.subtype = "Discharge Summary"
        else:
            info.subtype = "Medical Record"

        patient_name = extract_person_from_medical(text)
        norm_patient = normalize_person_name(patient_name, people)
        if fn_is_priority:
            info.person = fn_person
        elif norm_patient:
            info.person = norm_patient
        elif fn_person:
            info.person = fn_person
        else:
            info.person = people[0] if (people and len(people) == 1) else get_default_primary_user()
        info.reason = "Health / medical record identified"
        return info

    # -------------------------------------------------------------
    # 6. OTHER PERSONAL PAPERS (Taxes, Banking, Legal)
    # -------------------------------------------------------------
    if any(k in combined_low for k in ('itr', 'income tax return', 'tax assessment', '26as')):
        info.doc_type = "Taxes"
        info.subtype = "ITR"
        info.confidence = 0.88
        info.person = fn_person or (people[0] if (people and len(people) == 1) else get_default_primary_user())
        info.reason = "Tax return filing record identified"
        return info

    if any(k in combined_low for k in ('bank statement', 'account statement', 'passbook')):
        info.doc_type = "Banking"
        info.subtype = "Statement"
        info.confidence = 0.85
        info.person = fn_person or (people[0] if (people and len(people) == 1) else get_default_primary_user())
        info.reason = "Bank statement identified"
        return info

    # -------------------------------------------------------------
    # 7. DYNAMIC CONTEXTUAL TOPIC DISCOVERY (On-The-Spot Synthesis)
    # Extracts topics, projects, subjects, office work, domains, etc.
    # -------------------------------------------------------------
    ctx = extract_contextual_topic(filename, text, rel_dir, people)
    if ctx.confidence >= 0.80:
        info.topic = ctx.topic
        info.subtopic = ctx.subtopic
        info.project = ctx.project
        info.company = ctx.company
        info.domain = ctx.domain
        info.context_path = ctx.context_path
        info.doc_type = ctx.topic
        info.confidence = max(info.confidence, ctx.confidence)
        info.reason = ctx.reason
        if fn_is_priority and not info.person:
            info.person = fn_person
        return info

    # If person detected from filename or provenance even if general doc
    if fn_person and fn_is_priority:
        info.person = fn_person
        info.confidence = fn_conf

    return info
