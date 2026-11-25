"""Deterministic classifier with strict extension isolation.

No API key needed. It scores every category/subcategory against the words that
appear in the filename, the folder path and the first pages of the file itself.
This is the safety net under the LLM, and it is also what makes the tool work
completely offline.

Matching is token based, not raw substring, so "sdk" does not match "asdkjhqwe"
and "notes" does not outvote "call notes".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .scanner import FileInfo

_TOKEN = re.compile(r"[a-z0-9]+")
# keywords containing these are matched as raw substrings (requirements.txt, c++)
_LITERAL_CHARS = set(".-_/+")

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif",
    ".bmp", ".tiff", ".tif", ".avif", ".raw", ".cr2", ".nef", ".dng", ".arw", ".ico", ".svg",
}
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".wmv", ".m4v", ".webm", ".flv", ".3gp", ".ts", ".vob",
}
AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".opus", ".wav", ".aiff", ".mid", ".midi",
}
DOCUMENT_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".odt", ".rtf", ".txt", ".epub", ".mobi", ".azw3",
    ".xlsx", ".xls", ".ods", ".csv", ".tsv", ".pptx", ".ppt", ".odp", ".key",
    ".md", ".markdown", ".rst", ".tex", ".djvu",
}
ARCHIVE_EXTENSIONS = {
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".iso", ".cab", ".dmg",
}
INSTALLER_EXTENSIONS = {
    ".exe", ".msi", ".msix", ".appx", ".apk", ".deb", ".rpm",
}
CODE_EXTENSIONS = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".java", ".c", ".h",
    ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".sh", ".ps1", ".bat",
    ".cmd", ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".kt", ".swift",
    ".sql", ".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env",
}


@dataclass
class Verdict:
    category: str
    subcategory: str
    confidence: float
    reason: str
    method: str = "rules"


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def _pad(text: str) -> str:
    return " " + " ".join(_TOKEN.findall(text.lower())) + " "


def _hit(keyword: str, raw: str, padded: str, tokens: set[str]) -> bool:
    """Does this keyword appear as a real word (or standard English plural) in the text?"""
    kw = keyword.strip().lower()
    if not kw:
        return False
    if any(ch in _LITERAL_CHARS for ch in kw):
        return kw in raw
    if f" {kw} " in padded:
        return True
    for t in tokens:
        if t == kw:
            return True
        # Exact plurals / singulars:
        if kw.endswith(("s", "x", "z", "ch", "sh")) and t == kw + "es":
            return True
        elif not kw.endswith("s") and (t == kw + "s" or (len(kw) > 4 and kw == t + "s")):
            return True
    return False


def is_compatible(ext: str, category: str, subcategory: str, hints: set[str]) -> bool:
    """Hard physical isolation so JPGs never become videos, PDFs never become zips, etc."""
    if not ext:
        return True
    ext = ext.lower()
    cat = category.lower()
    sub = subcategory.lower()

    # Images
    if ext in IMAGE_EXTENSIONS:
        # A photo/image can NEVER be a video, music, zip, or installer
        if "video" in sub or "video" in cat or "youtube" in sub or "editing" in sub:
            return False
        if "music" in sub or "audio" in sub or "zip" in sub or "archive" in sub or "installer" in sub:
            return False
        if "media library" in cat:
            return sub in {"photos", "screenshots", "wallpapers & art"}
        if "creative projects" in cat:
            return sub in {"design & brand"}
        # Scanned documents / bills / IDs: only allow if OCR hint explicitly detected text/document
        if {"scan", "document", "text"} & hints:
            return True
        return sub in {"photos", "screenshots", "wallpapers & art", "design & brand", "needs review"}

    # Videos
    if ext in VIDEO_EXTENSIONS:
        if "photo" in sub or "wallpaper" in sub or "screenshot" in sub or "music" in sub or "zip" in sub:
            return False
        if cat in {"money & paperwork", "installers & software", "archive & old"}:
            return False
        return sub in {"personal video", "youtube & shorts", "editing & timelines", "courses", "needs review"}

    # Audio
    if ext in AUDIO_EXTENSIONS:
        if "photo" in sub or "video" in sub or "wallpaper" in sub or "zip" in sub or "document" in sub:
            return False
        return sub in {"music", "audio & music production", "courses", "needs review"}

    # Archives
    if ext in ARCHIVE_EXTENSIONS:
        if "photo" in sub or "video" in sub or "book" in sub or "invoice" in sub or "tax" in sub:
            return False
        return sub in {"zips & bundles", "old versions", "needs review"}

    # Documents (.pdf, .docx, .doc, .xlsx, etc.)
    if ext in DOCUMENT_EXTENSIONS:
        # A document can NEVER be a video, music, photo, wallpaper, timeline, zip bundle, or installer
        if sub in {
            "photos", "screenshots", "wallpapers & art", "personal video",
            "youtube & shorts", "editing & timelines", "music",
            "audio & music production", "zips & bundles", "installers", "drivers & firmware"
        }:
            return False
        if ext in {".epub", ".mobi", ".azw3", ".djvu"}:
            return sub in {"books & ebooks", "needs review"}
        if ext in {".pptx", ".ppt", ".key"}:
            return sub in {"pitches & decks", "courses", "needs review"}
        return True

    # Installers
    if ext in INSTALLER_EXTENSIONS:
        return sub in {"installers", "drivers & firmware", "needs review"}

    # Code
    if ext in CODE_EXTENSIONS:
        if "photo" in sub or "video" in sub:
            return False
        return True

    return True


class RuleEngine:
    def __init__(self, taxonomy: dict, fallback: dict[str, list[str]] | None = None):
        self.fallback = fallback or {}
        self.entries: list[dict] = []
        for cat in taxonomy.get("categories", []):
            cat_tokens = _tokens(cat["name"]) | _tokens(cat.get("description", ""))
            for sub in cat.get("subcategories", []):
                self.entries.append(
                    {
                        "category": cat["name"],
                        "subcategory": sub["name"],
                        "keywords": [k.lower() for k in sub.get("keywords", [])],
                        "cat_tokens": cat_tokens,
                        "sub_tokens": _tokens(sub["name"]),
                        "extensions": {e.lower() for e in sub.get("extensions", [])},
                        "is_fallback": sub["name"] == "Needs Review",
                    }
                )
        self.project_entry = next(
            (
                e for e in self.entries
                if e["subcategory"].lower() in {"projects & repos", "projects", "repos", "repositories"}
            ),
            None,
        )

    def classify(self, f: FileInfo) -> Verdict:
        name_raw = f.name.lower()
        name_pad = _pad(f.name)
        path_raw = f"{f.rel_dir} {f.name}".lower()
        path_pad = _pad(f"{f.rel_dir} {f.name}")
        body_raw = (f.text or "")[:4000].lower()
        body_pad = _pad(body_raw)
        name_tokens = set(name_pad.split())
        path_tokens = set(path_pad.split())
        body_tokens = set(body_pad.split())
        ext = f.ext.lower()
        hints = {h.lower() for h in getattr(f, "hints", []) or []}

        best: tuple[float, dict, list[str], bool, bool] | None = None
        for entry in self.entries:
            if entry["is_fallback"]:
                continue

            # Hard check: is file extension compatible with this category and subcategory?
            if not is_compatible(ext, entry["category"], entry["subcategory"], hints):
                continue

            score = 0.0
            hits: list[str] = []
            named = False
            ext_match = False
            body_score = 0.0

            for kw in entry["keywords"]:
                if _hit(kw, name_raw, name_pad, name_tokens):
                    score += 6.5
                    named = True
                    hits.append(kw)
                elif kw in hints:
                    score += 5.0
                    named = True
                    hits.append(kw)
                elif _hit(kw, path_raw, path_pad, path_tokens):
                    # Folder name match
                    score += 3.5
                    named = True
                    hits.append(kw)
                elif _hit(kw, body_raw, body_pad, body_tokens):
                    body_score += 1.8
                    hits.append(kw)

            # Cap body text match influence so internal text doesn't overrule clear titles
            body_only = (
                body_score
                + 0.6 * len(entry["sub_tokens"] & body_tokens)
                + 0.3 * len(entry["cat_tokens"] & body_tokens)
            )
            score += min(body_only, 2.5)

            if ext and ext in entry["extensions"]:
                score += 2.5
                ext_match = True

            if score > 0 and (best is None or score > best[0]):
                best = (score, entry, hits, named, ext_match)

        if best is None or best[0] < 1.0:
            return self._fallback(f)

        score, entry, hits, named, ext_match = best

        # Special check for directory bundles
        if f.is_dir and getattr(f, "kind", "") == "Document bundle":
            if entry["category"] in {"Learning & Reference", "Money & Paperwork",
                                     "Work & Clients", "Personal & Life"}:
                return Verdict(entry["category"], entry["subcategory"],
                               max(0.72, min(0.88, 0.35 + score / 18.0)),
                               "self-contained book/document set")
            return Verdict("Learning & Reference", "Books & Ebooks", 0.72,
                           "self-contained book/document set")

        # Project folder with .git or package.json
        if f.is_dir and score < 6.0 and self.project_entry:
            return Verdict(
                self.project_entry["category"],
                self.project_entry["subcategory"],
                0.62,
                "project folder (marker files found)",
            )

        if not hits:
            return self._fallback(f)

        confidence = min(0.96, 0.38 + score / 16.0)

        if not named and not ext_match:
            confidence = min(confidence, 0.45)

        unique = _longest_first(hits)[:3]
        reason = "matched " + ", ".join(repr(h) for h in unique) if unique else f"extension match ({ext})"
        if not named and not ext_match:
            reason = "weak: " + reason + " (inside the file only)"
        return Verdict(entry["category"], entry["subcategory"], round(confidence, 2), reason)

    def _fallback(self, f: FileInfo) -> Verdict:
        ext = f.ext.lower()
        pair = self.fallback.get(ext)
        if pair and len(pair) == 2:
            return Verdict(pair[0], pair[1], 0.60, f"file kind fallback ({ext})")
        # Smart default fallbacks
        if ext in IMAGE_EXTENSIONS:
            return Verdict("Media Library", "Photos", 0.60, f"image file ({ext})")
        if ext in VIDEO_EXTENSIONS:
            return Verdict("Media Library", "Personal Video", 0.60, f"video file ({ext})")
        if ext in AUDIO_EXTENSIONS:
            return Verdict("Media Library", "Music", 0.60, f"audio file ({ext})")
        if ext in ARCHIVE_EXTENSIONS:
            return Verdict("Archive & Old", "Zips & Bundles", 0.60, f"archive file ({ext})")
        if ext in INSTALLER_EXTENSIONS:
            return Verdict("Installers & Software", "Installers", 0.60, f"installer file ({ext})")
        if ext in {".epub", ".mobi", ".azw3", ".djvu"}:
            return Verdict("Learning & Reference", "Books & Ebooks", 0.65, f"ebook file ({ext})")
        if ext in {".pdf", ".docx", ".doc"}:
            return Verdict("Learning & Reference", "Books & Ebooks", 0.52, f"document ({ext})")
        return Verdict("Unsorted", "Needs Review", 0.10, "nothing matched")


def _longest_first(hits: list[str]) -> list[str]:
    """Drop keywords that are just a fragment of a longer matched keyword."""
    ordered = sorted(dict.fromkeys(hits), key=len, reverse=True)
    kept: list[str] = []
    for kw in ordered:
        if not any(kw in other for other in kept):
            kept.append(kw)
    return kept
