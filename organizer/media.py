"""Understand an image without a vision model.

The point of this project is "read the file and work out what it is FOR". For
photos that used to mean nothing: every .jpg fell into one folder by extension,
which is the "images ek sath" bucket we explicitly do not want.

You do not always need a neural net for this. A surprising amount of what an
image *is* can be read straight out of the file, with zero dependencies:

  * pixels      - width/height, aspect ratio, horizontal or vertical
  * EXIF        - camera make/model, capture date, GPS
  * container   - JPEG vs PNG vs WebP, EXIF present or absent
  * filename    - "Screenshot 2024-01-02", "WhatsApp Image", "IMG_3301"

From that we can tell a phone photo from a screenshot from an OEM wallpaper from
a downloaded stock asset. Not the *subject* of the photo, but its role - which
is what actually decides where a file belongs.

If a local vision model (e.g. Ollama + llava) is configured later, it can be
asked for one short sentence and appended; this module is the floor, not the
ceiling.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import NamedTuple

# Name tokens that reliably describe an image's provenance.
_SCREENSHOT_WORDS = ("screenshot", "screen shot", "snipping", "snip", "grab")
_SOCIAL_WORDS = ("whatsapp", "telegram", "instagram", "igg", "facebook", "signal")
_STOCK_WORDS = ("wallpaper", "background", "default", "option", "stock", "banner", "cover")
_SCAN_WORDS = ("scan", "scanned", "scanner", "camscanner", "adobe scan", "received")

_RES_TOKEN = re.compile(r"(?<!\d)(\d{3,5})\s*[x×]\s*(\d{3,5})(?!\d)")

# EXIF tag ids we care about
_TAG_MAKE = 0x010F
_TAG_MODEL = 0x0110
_TAG_DATETIME = 0x0132
_TAG_EXIF_IFD = 0x8769
_TAG_ORIGINAL = 0x9003


class ImageFacts(NamedTuple):
    width: int
    height: int
    fmt: str
    make: str
    model: str
    taken: str
    has_exif: bool

    @property
    def megapixels(self) -> float:
        return round(self.width * self.height / 1_000_000, 1)

    @property
    def orientation(self) -> str:
        if not self.width or not self.height:
            return ""
        ratio = self.width / self.height
        if ratio > 1.15:
            return "landscape"
        if ratio < 0.87:
            return "portrait"
        return "square"


def read_facts(path: Path) -> ImageFacts | None:
    """Best effort. Returns None when the file is not a readable image."""
    try:
        head = path.open("rb").read(64 * 1024)
    except OSError:
        return None
    if not head:
        return None

    fmt = ""
    width = height = 0
    make = model = taken = ""
    has_exif = False

    if head[:3] == b"\xff\xd8\xff":
        fmt = "jpeg"
        width, height, exif = _jpeg(head)
        if exif:
            has_exif = True
            make, model, taken = _exif_fields(exif)
    elif head[:8] == b"\x89PNG\r\n\x1a\n":
        fmt = "png"
        if len(head) >= 24 and head[12:16] == b"IHDR":
            width, height = struct.unpack(">II", head[16:24])
        has_exif = b"eXIf" in head
    elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        fmt = "webp"
        width, height = _webp_size(head)

    if not fmt:
        return None
    return ImageFacts(width, height, fmt, make.strip(), model.strip(), taken.strip(), has_exif)


# ------------------------------------------------------------------ formats

def _jpeg(blob: bytes) -> tuple[int, int, bytes]:
    """Walk JPEG segments: find the size from SOFn, collect the APP1/Exif block."""
    i = 2
    n = len(blob)
    exif = b""
    width = height = 0
    while i + 4 <= n:
        if blob[i] != 0xFF:
            i += 1
            continue
        marker = blob[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seglen = struct.unpack(">H", blob[i + 2 : i + 4])[0]
        if seglen < 2:
            break
        body = blob[i + 4 : i + 2 + seglen]
        if marker == 0xE1 and body[:6] == b"Exif\x00\x00":
            exif = body[6:]
        elif 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if len(body) >= 5:
                height, width = struct.unpack(">HH", body[1:5])
        if width and exif:
            break
        i += 2 + seglen
    return width, height, exif


def _webp_size(blob: bytes) -> tuple[int, int]:
    chunk = blob[12:16]
    try:
        if chunk == b"VP8X" and len(blob) >= 30:
            w = int.from_bytes(blob[24:27], "little") + 1
            h = int.from_bytes(blob[27:30], "little") + 1
            return w, h
        if chunk == b"VP8 " and len(blob) >= 30:
            w, h = struct.unpack("<HH", blob[26:30])
            return w & 0x3FFF, h & 0x3FFF
    except (struct.error, IndexError):
        pass
    return 0, 0


def _exif_fields(exif: bytes) -> tuple[str, str, str]:
    """Pull Make / Model / DateTimeOriginal out of a TIFF block."""
    if len(exif) < 8:
        return "", "", ""
    endian = "<" if exif[:2] == b"II" else ">"
    try:
        ifd0 = struct.unpack(endian + "I", exif[4:8])[0]
        make, model, taken = "", "", ""
        exif_ifd = 0
        for tag, value in _ifd_entries(exif, ifd0, endian):
            if tag == _TAG_MAKE:
                make = value
            elif tag == _TAG_MODEL:
                model = value
            elif tag == _TAG_DATETIME:
                taken = value
            elif tag == _TAG_EXIF_IFD:
                try:
                    exif_ifd = int(value)
                except ValueError:
                    pass
        if not taken and exif_ifd:
            for tag, value in _ifd_entries(exif, exif_ifd, endian):
                if tag == _TAG_ORIGINAL:
                    taken = value
                    break
        return make, model, taken
    except (struct.error, IndexError, ValueError):
        return "", "", ""


def _ifd_entries(blob: bytes, offset: int, endian: str):
    """Yield (tag, ascii value) for each string entry in one IFD."""
    if offset <= 0 or offset + 2 > len(blob):
        return
    count = struct.unpack(endian + "H", blob[offset : offset + 2])[0]
    if count > 512:
        return
    base = offset + 2
    for k in range(count):
        at = base + k * 12
        if at + 12 > len(blob):
            return
        tag = struct.unpack(endian + "H", blob[at : at + 2])[0]
        field_type = struct.unpack(endian + "H", blob[at + 2 : at + 4])[0]
        num = struct.unpack(endian + "I", blob[at + 4 : at + 8])[0]
        if field_type not in (2, 7) or num == 0 or num > 512:
            continue
        if num <= 4:
            raw = blob[at + 8 : at + 8 + num]
        else:
            ptr = struct.unpack(endian + "I", blob[at + 8 : at + 12])[0]
            if ptr + num > len(blob):
                continue
            raw = blob[ptr : ptr + num]
        yield tag, raw.rstrip(b"\x00").decode("ascii", "ignore")


# ------------------------------------------------------------------ meaning

def describe(path: Path) -> tuple[str, list[str]]:
    """Return (words for the classifier, short hint tags).

    Hints are the trusted evidence passed to the rules engine, e.g.
    ["screenshot"], ["photo", "camera"], ["wallpaper"].
    """
    name = path.name.lower()
    flat = name.replace("_", " ").replace("-", " ").replace(".", " ")
    facts = read_facts(path)
    hints: list[str] = []
    words: list[str] = []

    def has(collection) -> bool:
        return any(w in flat for w in collection)

    # provenance, strongest signal first
    if has(_SCREENSHOT_WORDS):
        hints += ["screenshot"]
        words.append("screen capture of an app or webpage")
    elif has(_SCAN_WORDS):
        hints += ["scan", "document"]
        words.append("scanned paper document")
    elif has(_SOCIAL_WORDS):
        hints += ["social", "photo"]
        words.append("picture received through a messaging app")
    elif has(_STOCK_WORDS):
        hints += ["wallpaper", "art"]
        words.append("stock artwork or desktop wallpaper")

    if facts:
        # A camera's make/model only appears when a real camera (or phone) took
        # the picture. That is the clearest "this is a personal photo" signal.
        if facts.make or facts.model:
            hints += ["photo", "camera"]
            words.append(f"photograph taken with {facts.make} {facts.model}".strip())
        elif facts.fmt == "png" and not hints:
            hints += ["screenshot"]
            words.append("lossless screenshot-like capture")
        if facts.taken:
            words.append(f"taken {facts.taken}")
        words.append(f"{facts.width}x{facts.height} {facts.orientation} {facts.megapixels} megapixels")

        # A filename that states the exact pixel size and has no camera metadata
        # is almost always a downloadable wallpaper or stock asset.
        res = _RES_TOKEN.search(flat)
        if res and not (facts.make or facts.model):
            try:
                if (int(res.group(1)), int(res.group(2))) == (facts.width, facts.height):
                    if "wallpaper" not in hints:
                        hints += ["wallpaper", "art"]
                    words.append("named with its own resolution")
            except ValueError:
                pass

    words.append(flat.strip())

    if not facts:
        words.append("image file")
    return " ".join(w for w in words if w), hints
