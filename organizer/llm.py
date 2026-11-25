"""LLM classifier. Works with any OpenAI-compatible endpoint, zero dependencies.

The model is only ever asked for a label. It cannot move a file.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import Config
from .rules import Verdict
from .scanner import FileInfo

SYSTEM = """You are a file-librarian. You place a person's computer files into their
personal "wardrobe" of folders.

Rules:
- Choose the most fitting category and subcategory from the provided taxonomy, OR synthesize a dynamic contextual folder hierarchy on the spot (e.g. "NASA" / "James_Webb_Space_Telescope", "Cinri Health API", "Office_Work" / "Vendor_Invoices_Q3", "Machine_Learning_Transformers", "Organic_Chemistry") if the file clearly belongs to a specific project, company, entity, or domain.
- Judge by what the file is FOR, not by its file format. A PDF invoice and a
  PDF novel belong in different places.
- Prefer a specific subcategory or discovered project over a generic one.
- If the content is genuinely unclear, use the "Unsorted" / "Needs Review" pair
  and give a low confidence.
- confidence is a number from 0 to 1. Be honest: 0.9+ only when certain.
- reason must be one short sentence, max 15 words.

Reply with a JSON array only. No prose, no markdown fences.
Each element: {"id": "...", "category": "...", "subcategory": "...", "confidence": 0.0, "reason": "..."}
"""


@dataclass
class LlmResult:
    verdicts: dict[str, Verdict]
    error: str = ""


def taxonomy_brief(tax: dict) -> str:
    lines = []
    for cat in tax.get("categories", []):
        subs = ", ".join(s["name"] for s in cat.get("subcategories", []))
        lines.append(f'- {cat["name"]}: {subs}\n  ({cat.get("description", "").strip()})')
    return "\n".join(lines)


def _payload(files: list[FileInfo]) -> str:
    docs = []
    for f in files:
        docs.append(
            {
                "id": f.id,
                "filename": f.name,
                "folder": f.rel_dir or "(root)",
                "kind": f.kind,
                "size_kb": round(f.size / 1024, 1),
                "excerpt": (f.text or "")[:700].replace("\n", " ").strip(),
            }
        )
    return json.dumps(docs, ensure_ascii=False)


def classify(cfg: Config, taxonomy: dict, files: list[FileInfo]) -> LlmResult:
    if not cfg.llm.usable or not files:
        return LlmResult({}, "llm unavailable")

    url = f"{cfg.llm.base_url}/chat/completions"
    verdicts: dict[str, Verdict] = {}
    errors: list[str] = []
    brief = taxonomy_brief(taxonomy)
    valid = _valid_pairs(taxonomy)

    for i in range(0, len(files), cfg.llm.batch_size):
        batch = files[i : i + cfg.llm.batch_size]
        user = (
            f"TAXONOMY\n{brief}\n\n"
            f"FILES\n{_payload(batch)}\n\n"
            "Return the JSON array now."
        )
        body = {
            "model": cfg.llm.model,
            "temperature": cfg.llm.temperature,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
            ],
        }
        try:
            raw = _post(url, body, cfg.llm.api_key, cfg.llm.timeout_seconds)
        except Exception as exc:  # network, auth, timeout
            errors.append(str(exc))
            break

        for item in _parse_array(raw):
            fid = str(item.get("id", ""))
            cat = str(item.get("category", "")).strip()
            sub = str(item.get("subcategory", "")).strip()
            if not fid or not cat:
                continue
            is_valid_pair = (cat, sub) in valid
            # Allow dynamic contextual topics synthesized on the spot by LLM
            is_dynamic = bool(getattr(cfg, "dynamic_context_folders", True) and cat and cat != "Unsorted")
            if not is_valid_pair and not is_dynamic:
                continue
            try:
                conf = float(item.get("confidence", 0.5))
            except (TypeError, ValueError):
                conf = 0.5
            ctx_path = [cat, sub] if (not is_valid_pair and sub and sub != cat) else ([cat] if not is_valid_pair else [])
            verdicts[fid] = Verdict(
                category=cat,
                subcategory=sub or cat,
                confidence=max(0.0, min(1.0, conf)),
                reason=str(item.get("reason", ""))[:160],
                method="llm",
                topic=cat if not is_valid_pair else "",
                subtopic=sub if not is_valid_pair else "",
                context_path=ctx_path,
            )
    return LlmResult(verdicts, "; ".join(errors))


def _valid_pairs(tax: dict) -> set[tuple[str, str]]:
    pairs = set()
    for cat in tax.get("categories", []):
        for sub in cat.get("subcategories", []):
            pairs.add((cat["name"], sub["name"]))
    return pairs


def _post(url: str, body: dict, api_key: str, timeout: int) -> str:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8", "ignore"))
    return payload["choices"][0]["message"]["content"]


def _parse_array(text: str) -> list[dict]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        # model may have returned a bare object
        start, end = text.find("{"), text.rfind("}")
        if start == -1:
            return []
        text = "[" + text[start : end + 1] + "]"
    else:
        text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        parsed = [parsed]
    return [x for x in parsed if isinstance(x, dict)]
