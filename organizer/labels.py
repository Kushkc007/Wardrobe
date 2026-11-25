"""On-the-spot folder labels.

No family, no document type and no folder list is defined here. The learner
looks at the actual files in the current scan and derives a short, human folder
name from:

    filename words  ->  "Kush_R1_SalarySlip_Aug.pdf"  -> "Salary Slip"
    document text   ->  first title-ish line          -> "Sale Deed"
    detected subtype->  e.g. Aadhaar / Payslip        -> only if the file
                                                         itself gave no name

Names are clustered as the scan runs, so "Salary Slip" and "Salary Slips" share
one folder. Any new phrase becomes a new folder the moment it is needed.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+\d*|[A-Z]+\d*|\d+")

GENERIC = {
    "img", "image", "images", "photo", "photos", "pic", "pics", "picture",
    "dsc", "dcim", "vid", "video", "videos", "whatsapp", "wa", "screenshot",
    "screen", "shot", "capture", "new", "old", "final", "copy", "edit",
    "edited", "original", "download", "downloads", "file", "files", "doc",
    "docs", "document", "documents", "scan", "scanned", "page", "part",
    "version", "update", "draft", "the", "and", "with", "from", "for", "of",
    "to", "in", "on", "at", "by", "pdf", "docx", "doc", "xlsx", "xls", "pptx",
    "ppt", "jpg", "jpeg", "png", "gif", "webp", "heic", "mp4", "mov", "mkv",
    "epub", "mobi", "zip", "rar", "txt", "csv", "json", "xml", "html",
    "misc", "other", "others", "general", "miscellaneous", "untitled",
    "jan", "january", "feb", "february", "mar", "march", "apr", "april",
    "may", "jun", "june", "jul", "july", "aug", "august", "sep", "sept",
    "september", "oct", "october", "nov", "november", "dec", "december",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}

KINSHIP = {
    "papa", "dad", "daddy", "father", "pitaji", "mummy", "mom", "mother",
    "mataji", "maa", "bhai", "bhaiya", "brother", "behen", "didi", "sister",
    "bua", "buaji", "chacha", "chachi", "mama", "mami", "dada", "dadi",
    "nanu", "nani", "beta", "beti", "wife", "husband", "son", "daughter",
    "self", "me", "my",
}

ADDRESS_HINTS = {
    "road", "street", "lane", "nagar", "colony", "sector", "block", "house",
    "flat", "plot", "pin", "district", "tehsil", "village", "post", "near",
    "behind", "opposite", "floor", "building", "apartment",
}

ORG_WORDS = {
    "authority", "department", "government", "corporation", "company",
    "limited", "ltd", "pvt", "private", "services", "solutions",
    "technologies", "university", "college", "school", "hospital", "clinic",
    "bank", "board", "council", "institute", "commission", "ministry",
}


def _tokens(text: str) -> list[str]:
    """Split camelCase and separators into readable words."""
    out: list[str] = []
    for chunk in re.split(r"[_\-.\\/()\[\]]+", str(text)):
        for tok in CAMEL_RE.findall(chunk):
            if tok and not tok.isdigit():
                out.append(tok)
    return out


def _clean_label(text: str) -> str:
    text = re.sub(r"[\r\n\t]+", " ", str(text))
    text = re.sub(r"[^A-Za-z0-9&' /]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .:-")
    # Form16 -> Form 16, Policy2024 -> Policy 2024 (the year is dropped next)
    text = re.sub(r"(?<=[A-Za-z])(\d{1,3})\b", r" \1", text)
    text = re.sub(r"\b(?:19|20)\d{2}\b", "", text)
    words = [w for w in text.split() if w.lower() not in GENERIC]
    if not words or len(words) > 5:
        return ""
    label = " ".join(words[:4]).strip()
    if len(label) < 2 or label.isdigit():
        return ""
    # keep short acronyms (PAN, ITR), title-case the rest naturally
    pretty = []
    for w in label.split():
        if w.isupper() and 2 <= len(w) <= 5:
            pretty.append(w)
        else:
            pretty.append(w[:1].upper() + w[1:].lower())
    return " ".join(pretty)


def _normalise_key(label: str) -> str:
    words = re.findall(r"[a-z0-9]+", label.lower())
    out = []
    for w in words:
        if w.endswith("ies") and len(w) > 4:
            w = w[:-3] + "y"
        elif w.endswith(("ches", "shes", "xes", "ses")):
            w = w[:-2]
        elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
            w = w[:-1]
        out.append(w)
    return " ".join(out)


@dataclass
class LabelSuggestion:
    file_id: str
    label: str
    source: str
    score: float = 0.0


class LabelLearner:
    """Learn folder names from this scan - there is no predefined folder list."""

    def __init__(self, people: list[str] | None = None, companies: list[str] | None = None):
        self.exclude: set[str] = set(GENERIC) | set(KINSHIP)
        for name in list(people or []) + list(companies or []):
            self.exclude.update(w.lower() for w in _tokens(name))
        self.suggestions: dict[str, LabelSuggestion] = {}
        self.canonical: dict[str, str] = {}     # normalised key -> chosen label
        self._observed: list[LabelSuggestion] = []
        self._raw: dict[str, tuple] = {}

    # ------------------------------------------------------------------ fit

    def observe(self, file_id: str, filename: str, text: str = "", rel_dir: str = "",
                doc_info=None) -> None:
        # A name the document reader found must not leak into the folder label.
        person = str(getattr(doc_info, "person", "") or "")
        if person:
            self.exclude.update(w.lower() for w in _tokens(person))
        self._raw[file_id] = (filename, text, rel_dir, doc_info)
        suggestion = self._suggest(filename, text, rel_dir, doc_info)
        self.suggestions[file_id] = suggestion
        if suggestion.label:
            self._observed.append(suggestion)

    def finalize(self) -> None:
        """Cluster equal/similar labels and choose one representative."""
        # Re-read every file now that all names found in any document are known.
        # This keeps "Kush Resume" from surviving in file 1 when file 2 proves
        # that Kush is a person, not a folder word.
        self.suggestions = {}
        self._observed = []
        for file_id, (filename, text, rel_dir, doc_info) in self._raw.items():
            suggestion = self._suggest(filename, text, rel_dir, doc_info)
            self.suggestions[file_id] = suggestion
            if suggestion.label:
                self._observed.append(suggestion)

        buckets: dict[str, list[str]] = defaultdict(list)
        for s in self._observed:
            buckets[_normalise_key(s.label)].append(s.label)

        # exact-normalised buckets -> most frequent spelling
        chosen = {}
        for key, labels in buckets.items():
            counts = Counter(labels)
            chosen[key] = sorted(counts, key=lambda l: (-counts[l], len(l)))[0]

        # merge near-duplicates: {"aadhaar card"} with {"aadhaar"}
        keys = list(chosen)
        merged: dict[str, str] = {}
        for i, key in enumerate(keys):
            if key in merged:
                continue
            merged[key] = chosen[key]
            kt = set(key.split())
            for other in keys[i + 1:]:
                if other in merged:
                    continue
                ot = set(other.split())
                if not kt or not ot:
                    continue
                overlap = len(kt & ot) / max(len(kt), len(ot))
                if overlap >= 0.6 or kt <= ot or ot <= kt:
                    # prefer the shorter, cleaner label
                    merged[other] = chosen[key] if len(chosen[key]) <= len(chosen[other]) else chosen[other]

        self.canonical = merged
        # make the chosen spelling stable for every suggestion
        for s in self._observed:
            key = _normalise_key(s.label)
            s.label = self.canonical.get(key, chosen.get(key, s.label))

    def label_for(self, file_id: str) -> str:
        s = self.suggestions.get(file_id)
        if not s or not s.label:
            return ""
        return self.canonical.get(_normalise_key(s.label), s.label)

    # -------------------------------------------------------------- suggest

    def _suggest(self, filename: str, text: str, rel_dir: str, doc_info) -> LabelSuggestion:
        # 1. The user's own filename is the strongest, most personal signal.
        name_label = self._from_filename(filename)
        if name_label:
            return LabelSuggestion("", name_label, "filename", 0.9)

        # 2. A detected concrete subtype (Aadhaar, Payslip, Prescription) is
        #    the file's own classification, not a folder taxonomy.
        subtype = str(getattr(doc_info, "subtype", "") or "").strip()
        if subtype and subtype.lower() not in {"cv", "identity id", "biometric"}:
            label = _clean_label(subtype)
            if label:
                return LabelSuggestion("", label, "detected-type", 0.85)

        # 3. Read the document's own heading.
        text_label = self._from_text(text)
        if text_label:
            return LabelSuggestion("", text_label, "text", 0.8)

        # 4. A softer subtype (Resume / Health / Banking) is still the file's
        #    classification, so use it rather than inventing a folder.
        doc_type = str(getattr(doc_info, "doc_type", "") or "").strip()
        if doc_type and doc_type.lower() not in {"custom"}:
            label = _clean_label(doc_type)
            if label:
                return LabelSuggestion("", label, "detected-type", 0.75)
        return LabelSuggestion("", "", "", 0.0)

    def _from_filename(self, filename: str) -> str:
        stem = Path(filename).stem
        words = []
        for tok in _tokens(stem):
            low = tok.lower()
            if low in self.exclude or low.isdigit() or len(low) < 2:
                continue
            # camera / WhatsApp noise like IMG_2024, WA0001, DSC0123
            if re.fullmatch(r"(?:wa|img|dsc|vid|mvimg|pxl|photo|image)\d*", low):
                continue
            words.append(tok)
        # collapse obvious repeats ("salary slip slip")
        deduped: list[str] = []
        for w in words:
            if not deduped or deduped[-1].lower() != w.lower():
                deduped.append(w)
        if not deduped:
            return ""
        # prefer the longest run of meaningful words, capped at 4
        return _clean_label(" ".join(deduped[:4]))

    def _from_text(self, text: str) -> str:
        if not text:
            return ""
        lines = [re.sub(r"\s+", " ", l).strip() for l in text[:4000].splitlines()]
        best = ""
        best_score = 0.0
        for i, line in enumerate(lines[:40]):
            if not (3 <= len(line) <= 70):
                continue
            low = line.lower()
            if "@" in line or "http" in low or re.search(r"\b\d{5,}\b", line):
                continue
            words = re.findall(r"[A-Za-z][A-Za-z'&.-]*", line)
            if not (1 <= len(words) <= 7):
                continue
            if all(w.lower() in self.exclude for w in words):
                continue
            if any(w.lower() in ADDRESS_HINTS for w in words):
                continue
            score = 2.0
            if line.isupper() or line.istitle():
                score += 1.5
            if any(w.lower().rstrip(".") in ORG_WORDS for w in words):
                score += 0.8
            if line.endswith(":"):
                score -= 1.0
            if any(ch.isdigit() for ch in line):
                score -= 1.5
            score -= i * 0.04
            if score > best_score:
                best_score = score
                best = line
        return _clean_label(best) if best_score >= 2.4 else ""

    # -------------------------------------------------------------- helpers

    def known_label(self, label: str) -> str:
        return self.canonical.get(_normalise_key(label), label)


def make_learner(profile, cfg) -> LabelLearner:
    people: list[str] = []
    companies: list[str] = []
    if profile is not None:
        for p in profile.people:
            people.append(p.name)
            people.extend(p.aliases)
            companies.extend(p.companies)
    people.extend(getattr(cfg, "people", []) or [])
    return LabelLearner(people=people, companies=companies)
