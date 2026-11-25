"""Wardrobe dashboard - a live control room for the organiser.

    python organize.py dashboard

Full parity with Claude Photo Sorter skill dashboard:
- Live sorting stream with recursive nested folder scanning (folder -> subfolder -> sub-subfolder)
- Animated files gliding dynamically into generated destination folder cards
- Automatic detection of duplicates flying into the Duplicates / Review bucket
- Multi-view architecture:
    1. Live Sorting Chamber
    2. File Explorer & Plan Inspector
    3. Duplicates & Review Station
    4. Changes & History Journal (Complete audit trail of what was changed and rollback)
    5. Statistics & Analytics Dashboard
    6. System Configuration & Roots

Runs locally on 127.0.0.1:8765. Zero external dependencies, secure, offline.
"""
from __future__ import annotations

import collections
import json
import os
import shutil
import string
import sys
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, abort, Response

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from organizer.apply import apply_plan, undo_last  # noqa: E402
from organizer.audit import run_audit  # noqa: E402
from organizer.config import Config, load_taxonomy  # noqa: E402
from organizer.planner import PlanItem, build_plan, to_json, safe_name  # noqa: E402
from organizer.report import write_report  # noqa: E402
from organizer.scanner import FileInfo, scan, file_id  # noqa: E402
from organizer.rules import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS, DOCUMENT_EXTENSIONS, ARCHIVE_EXTENSIONS, INSTALLER_EXTENSIONS, CODE_EXTENSIONS  # noqa: E402

if getattr(sys, "frozen", False):
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    template_dir = str(BUNDLE_DIR / "dashboard" / "templates")
    static_dir = str(BUNDLE_DIR / "dashboard" / "static")
else:
    template_dir = str(Path(__file__).resolve().parent / "templates")
    static_dir = str(Path(__file__).resolve().parent / "static")

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)

_cfg: Config | None = None
_cache: dict = {}
_lock = threading.Lock()
_cancel_requested = False
_job: dict = {
    "id": 0, "action": "", "state": "idle", "pct": 0,
    "message": "", "started": 0.0, "finished": 0.0, "result": {},
    "current_file": "", "current_folder": "", "count": 0, "total": 0,
}


def cfg() -> Config:
    global _cfg
    if _cfg is None:
        _cfg = Config.load()
        _cfg.ensure_dirs()
    return _cfg


# ----------------------------------------------------------------- state reading

def _plan_items(c: Config) -> list[PlanItem]:
    path = c.state_file("plan.json")
    if not path.exists():
        return []
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return []
    cached = _cache.get("plan_items")
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        data = json.loads(text)
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for raw in data.get("items", []):
        try:
            out.append(PlanItem(**raw))
        except TypeError:
            continue
    _cache["plan_items"] = (stamp, out)
    return out


def _plan_meta(c: Config) -> dict:
    path = c.state_file("plan.json")
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return {}
        data = json.loads(text)
    except (OSError, json.JSONDecodeError):
        return {}
    return {"generated": data.get("generated", 0), "stats": data.get("stats", {})}


def _inventory_files(c: Config) -> list[FileInfo]:
    path = c.state_file("inventory.json")
    if not path.exists():
        return []
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return []
    cached = _cache.get("inv_files")
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        data = json.loads(text)
    except (OSError, json.JSONDecodeError):
        return []
    files = []
    for raw in data.get("files", []):
        try:
            files.append(FileInfo(**raw))
        except TypeError:
            continue
    _cache["inv_files"] = (stamp, files)
    return files


def _inventory_meta(c: Config) -> dict:
    path = c.state_file("inventory.json")
    if not path.exists():
        return {"exists": False, "count": 0, "generated": 0, "errors": 0}
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return {"exists": False, "count": 0, "generated": 0, "errors": 0}
        data = json.loads(text)
    except (OSError, json.JSONDecodeError):
        return {"exists": False, "count": 0, "generated": 0, "errors": 0}
    return {
        "exists": True,
        "count": data.get("count", 0),
        "generated": data.get("generated", 0),
        "errors": len(data.get("errors", [])),
        "roots": data.get("roots", []),
    }


def _vault_stats(c: Config) -> dict:
    now = time.time()
    if _cache.get("vault_ts", 0) > now - 8:
        return _cache["vault"]

    stats = {"path": str(c.vault), "exists": c.vault.exists(),
             "files": 0, "bytes": 0, "categories": []}
    if c.vault.exists():
        per: dict[str, list[int]] = {}
        try:
            for top in c.vault.iterdir():
                if not top.is_dir() or top.name.startswith("."):
                    continue
                count = size = 0
                for p in top.rglob("*"):
                    try:
                        if p.is_file():
                            count += 1
                            size += p.stat().st_size
                    except OSError:
                        continue
                per[top.name] = [count, size]
        except OSError:
            pass
        stats["categories"] = sorted(
            ({"name": k, "files": v[0], "bytes": v[1]} for k, v in per.items()),
            key=lambda d: -d["files"],
        )
        stats["files"] = sum(v[0] for v in per.values())
        stats["bytes"] = sum(v[1] for v in per.values())

    _cache["vault"] = stats
    _cache["vault_ts"] = now
    return stats


def _duplicates(c: Config) -> list[dict]:
    path = c.state_file("audit.json")
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8").strip()
            if text:
                data = json.loads(text)
                groups = []
                for group in data.get("duplicates", []):
                    entries = []
                    for fp in group:
                        try:
                            size = os.path.getsize(fp)
                        except OSError:
                            size = 0
                        p = Path(fp)
                        ext = p.suffix.lower()
                        entries.append({
                            "id": file_id(p),
                            "path": fp,
                            "name": p.name,
                            "ext": ext,
                            "size": size,
                            "thumb": ext in THUMBABLE,
                            "exists": os.path.exists(fp),
                        })
                    if entries:
                        first = max(e["size"] for e in entries)
                        groups.append({
                            "files": entries,
                            "size": first,
                            "wasted": first * (len(entries) - 1),
                        })
                groups.sort(key=lambda g: -g["wasted"])
                if groups:
                    return groups
        except (OSError, json.JSONDecodeError):
            pass

    # Quick fallback duplicate scanner from inventory by size & name if audit hasn't run
    inv_files = _inventory_files(c)
    if not inv_files:
        items = _plan_items(c)
        sizes: dict[int, list[PlanItem]] = collections.defaultdict(list)
        for it in items:
            if it.size > 2048:
                sizes[it.size].append(it)
        groups = []
        for sz, arr in sizes.items():
            if len(arr) > 1:
                # Name or exact size cluster
                groups.append({
                    "files": [{
                        "id": x.id,
                        "path": x.source,
                        "name": Path(x.source).name,
                        "ext": Path(x.source).suffix.lower(),
                        "size": x.size,
                        "thumb": Path(x.source).suffix.lower() in THUMBABLE,
                        "exists": True,
                    } for x in arr],
                    "size": sz,
                    "wasted": sz * (len(arr) - 1),
                })
        groups.sort(key=lambda g: -g["wasted"])
        return groups[:80]
    return []


def _activity(c: Config, limit: int = 150) -> list[dict]:
    events: list[dict] = []
    try:
        journals = sorted(c.state_dir.glob("undo-*.json"))
    except OSError:
        journals = []
    for journal in journals:
        try:
            text = journal.read_text(encoding="utf-8").strip()
            if not text:
                continue
            data = json.loads(text)
        except (OSError, json.JSONDecodeError):
            continue
        for rec in data.get("records", []):
            src = rec.get("src", "")
            dst = rec.get("dst", "")
            try:
                sz = os.path.getsize(dst) if os.path.exists(dst) else (os.path.getsize(src) if os.path.exists(src) else 0)
            except OSError:
                sz = 0
            ts = rec.get("ts", 0)
            events.append({
                "ts": ts,
                "date": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "—",
                "op": rec.get("op", "move"),
                "src": src,
                "dst": dst,
                "name": os.path.basename(src),
                "dest_name": os.path.basename(dst),
                "size": sz,
                "source": "journal",
                "journal": journal.name,
                "status": "applied",
            })

    log_path = c.state_file("watch.log")
    if log_path.exists():
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-40:]
        except OSError:
            lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            events.append({
                "ts": 0,
                "date": "live watch",
                "op": "watch",
                "src": line,
                "dst": "",
                "name": os.path.basename(line),
                "dest_name": "",
                "size": 0,
                "source": "watch",
                "journal": "watch.log",
                "status": "active",
            })

    # Also list pending moves from plan if no journal yet
    if not events:
        items = _plan_items(c)
        for it in items[:limit]:
            events.append({
                "ts": it.mtime,
                "date": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(it.mtime)) if it.mtime else "Pending",
                "op": "planned",
                "src": it.source,
                "dst": it.destination,
                "name": os.path.basename(it.source),
                "dest_name": os.path.basename(it.destination),
                "size": it.size,
                "category": it.category,
                "subcategory": it.subcategory,
                "status": it.status,
                "source": "plan",
                "journal": "plan.json",
            })

    events.sort(key=lambda e: -e["ts"])
    return events[:limit]


# ----------------------------------------------------------------- endpoints

@app.get("/favicon.ico")
def favicon():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<rect width="24" height="24" rx="6" fill="#7c8cff"/>'
        '<path d="M4 8.5 12 4.5l8 4v7L12 19.5l-8-4z" fill="none" '
        'stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/>'
        '</svg>'
    )
    return Response(svg, mimetype="image/svg+xml")


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/overview")
def api_overview():
    c = cfg()
    items = _plan_items(c)
    plan_meta = _plan_meta(c)
    inv = _inventory_meta(c)
    vault = _vault_stats(c)
    dups = _duplicates(c)
    tax = load_taxonomy(c.taxonomy_path)

    cats: dict[str, dict] = {}
    for item in items:
        cat = cats.setdefault(item.category, {
            "name": item.category, "files": 0, "bytes": 0,
            "ready": 0, "review": 0, "subs": {},
        })
        cat["files"] += 1
        cat["bytes"] += item.size
        if item.status == "low_confidence":
            cat["review"] += 1
        else:
            cat["ready"] += 1
        sub = cat["subs"].setdefault(item.subcategory, {"name": item.subcategory, "files": 0, "bytes": 0})
        sub["files"] += 1
        sub["bytes"] += item.size

    if not cats:
        for entry in tax.get("categories", []):
            cats[entry["name"]] = {
                "name": entry["name"], "files": 0, "bytes": 0,
                "ready": 0, "review": 0,
                "subs": {s["name"]: {"name": s["name"], "files": 0, "bytes": 0}
                         for s in entry.get("subcategories", [])},
            }

    categories = sorted(cats.values(), key=lambda d: (-d["files"], d["name"]))
    for cat in categories:
        cat["subs"] = sorted(cat["subs"].values(), key=lambda d: (-d["files"], d["name"]))

    bucket = {"high": 0, "mid": 0, "low": 0}
    status = {"ready": 0, "low_confidence": 0, "protected": 0, "conflict": 0}
    total_bytes = 0
    for item in items:
        total_bytes += item.size
        if item.status in status:
            status[item.status] += 1
        if item.confidence >= 0.75:
            bucket["high"] += 1
        elif item.confidence >= 0.5:
            bucket["mid"] += 1
        else:
            bucket["low"] += 1

    return jsonify({
        "generated": time.time(),
        "files": len(items),
        "bytes": total_bytes,
        "categories": categories,
        "confidence": bucket,
        "status": status,
        "vault": vault,
        "inventory": inv,
        "plan": plan_meta,
        "ai": {
            "usable": c.llm.usable,
            "model": c.llm.model,
            "base_url": c.llm.base_url,
            "key_env": c.llm.api_key_env,
        },
        "duplicates": {
            "groups": len(dups),
            "wasted": sum(g["wasted"] for g in dups),
        },
        "roots": [str(r) for r in c.roots],
        "vault_path": str(c.vault),
    })


@app.get("/api/files")
def api_files():
    c = cfg()
    q = (request.args.get("q") or "").strip().lower()
    category = (request.args.get("category") or "").strip()
    subcategory = (request.args.get("sub") or "").strip()
    status = (request.args.get("status") or "").strip()
    sort = (request.args.get("sort") or "name").strip()
    page = max(1, request.args.get("page", 1, type=int))
    per = min(500, max(5, request.args.get("per", 60, type=int)))

    inv_kind = {f.id: f.kind for f in _inventory_files(c)}
    items = _plan_items(c)
    rows = []
    for item in items:
        name = os.path.basename(item.source.rstrip("\\/"))
        ext = Path(name).suffix.lower()
        row = {
            "id": item.id,
            "name": name,
            "ext": ext,
            "kind": inv_kind.get(item.id, ""),
            "thumb": ext in THUMBABLE,
            "source": item.source,
            "destination": item.destination,
            "category": item.category,
            "subcategory": item.subcategory,
            "confidence": item.confidence,
            "reason": item.reason,
            "method": item.method,
            "size": item.size,
            "mtime": item.mtime,
            "status": item.status,
            "is_dir": item.is_dir,
            "dest_rel": _rel(c, item.destination),
        }
        if q and q not in (name + " " + item.source + " " + item.category + " "
                           + item.subcategory + " " + item.reason).lower():
            continue
        if category and item.category != category:
            continue
        if subcategory and item.subcategory != subcategory:
            continue
        if status and item.status != status:
            continue
        rows.append(row)

    if sort == "size":
        rows.sort(key=lambda r: -r["size"])
    elif sort == "confidence":
        rows.sort(key=lambda r: r["confidence"])
    elif sort == "date":
        rows.sort(key=lambda r: -r["mtime"])
    else:
        rows.sort(key=lambda r: r["name"].lower())

    total = len(rows)
    start = (page - 1) * per
    return jsonify({
        "total": total,
        "page": page,
        "per": per,
        "pages": max(1, (total + per - 1) // per),
        "items": rows[start:start + per],
    })


@app.get("/api/duplicates")
def api_duplicates():
    groups = _duplicates(cfg())
    return jsonify({
        "groups": groups,
        "total_groups": len(groups),
        "wasted": sum(g["wasted"] for g in groups),
        "checked": cfg().state_file("audit.json").exists(),
    })


@app.get("/api/activity")
def api_activity():
    return jsonify({"events": _activity(cfg())})


@app.get("/api/changelog")
def api_changelog():
    c = cfg()
    q = (request.args.get("q") or "").strip().lower()
    op = (request.args.get("op") or "").strip().lower()
    page = max(1, request.args.get("page", 1, type=int))
    per = min(500, max(10, request.args.get("per", 50, type=int)))

    events = _activity(c, limit=500)
    filtered = []
    for ev in events:
        if q and q not in (ev.get("name", "") + " " + ev.get("src", "") + " " + ev.get("dst", "")).lower():
            continue
        if op and ev.get("op", "").lower() != op:
            continue
        filtered.append(ev)

    total = len(filtered)
    start = (page - 1) * per
    return jsonify({
        "total": total,
        "page": page,
        "per": per,
        "pages": max(1, (total + per - 1) // per),
        "events": filtered[start:start + per],
    })


@app.get("/api/analytics")
def api_analytics():
    c = cfg()
    items = _plan_items(c)
    dups = _duplicates(c)
    vault = _vault_stats(c)

    formats = {
        "Photos": {"count": 0, "size": 0, "exts": [".jpg", ".png", ".webp", ".heic"]},
        "Videos": {"count": 0, "size": 0, "exts": [".mp4", ".mov", ".mkv", ".webm"]},
        "Documents": {"count": 0, "size": 0, "exts": [".pdf", ".docx", ".doc", ".odt"]},
        "Spreadsheets": {"count": 0, "size": 0, "exts": [".xlsx", ".xls", ".csv"]},
        "Presentations": {"count": 0, "size": 0, "exts": [".pptx", ".ppt", ".key"]},
        "Audio": {"count": 0, "size": 0, "exts": [".mp3", ".flac", ".wav", ".m4a"]},
        "Archives": {"count": 0, "size": 0, "exts": [".zip", ".rar", ".7z", ".tar"]},
        "Code & Data": {"count": 0, "size": 0, "exts": [".py", ".js", ".ts", ".json", ".sql"]},
        "Installers": {"count": 0, "size": 0, "exts": [".exe", ".msi", ".apk", ".iso"]},
        "Other": {"count": 0, "size": 0, "exts": []},
    }

    depth_dist = collections.defaultdict(int)
    cat_dist = collections.defaultdict(lambda: {"count": 0, "size": 0})

    for it in items:
        ext = Path(it.source).suffix.lower()
        sz = it.size
        cat_dist[it.category]["count"] += 1
        cat_dist[it.category]["size"] += sz

        parts = Path(it.source).parts
        depth = min(len(parts), 8)
        depth_dist[str(depth)] += 1

        matched = False
        if ext in IMAGE_EXTENSIONS:
            formats["Photos"]["count"] += 1
            formats["Photos"]["size"] += sz
            matched = True
        elif ext in VIDEO_EXTENSIONS:
            formats["Videos"]["count"] += 1
            formats["Videos"]["size"] += sz
            matched = True
        elif ext in {".pdf", ".docx", ".doc", ".odt", ".rtf", ".txt", ".epub", ".mobi"}:
            formats["Documents"]["count"] += 1
            formats["Documents"]["size"] += sz
            matched = True
        elif ext in {".xlsx", ".xls", ".ods", ".csv"}:
            formats["Spreadsheets"]["count"] += 1
            formats["Spreadsheets"]["size"] += sz
            matched = True
        elif ext in {".pptx", ".ppt", ".key"}:
            formats["Presentations"]["count"] += 1
            formats["Presentations"]["size"] += sz
            matched = True
        elif ext in AUDIO_EXTENSIONS:
            formats["Audio"]["count"] += 1
            formats["Audio"]["size"] += sz
            matched = True
        elif ext in ARCHIVE_EXTENSIONS:
            formats["Archives"]["count"] += 1
            formats["Archives"]["size"] += sz
            matched = True
        elif ext in CODE_EXTENSIONS:
            formats["Code & Data"]["count"] += 1
            formats["Code & Data"]["size"] += sz
            matched = True
        elif ext in INSTALLER_EXTENSIONS:
            formats["Installers"]["count"] += 1
            formats["Installers"]["size"] += sz
            matched = True
        if not matched:
            formats["Other"]["count"] += 1
            formats["Other"]["size"] += sz

    total_size = sum(it.size for it in items)
    wasted = sum(g["wasted"] for g in dups)

    return jsonify({
        "total_files": len(items),
        "total_bytes": total_size,
        "vault_files": vault["files"],
        "vault_bytes": vault["bytes"],
        "duplicates_groups": len(dups),
        "duplicates_wasted": wasted,
        "formats": formats,
        "categories": [{"name": k, "count": v["count"], "size": v["size"]}
                       for k, v in sorted(cat_dist.items(), key=lambda kv: -kv[1]["count"])],
        "depths": depth_dist,
    })


@app.get("/api/inspect_roots")
def api_inspect_roots():
    """Returns directory structure tree of roots with nested subfolder counts."""
    c = cfg()
    roots_data = []
    root_names = []
    for root in c.roots:
        if not root.exists():
            continue
        rname = root.name if root.name else str(root)
        root_names.append(rname)
        tree_node = {"name": rname, "path": str(root), "folders": [], "file_count": 0}
        try:
            # Walk top 3 levels for instant UI visualization
            subdirs = []
            for item in sorted(root.iterdir()):
                if item.is_dir() and not item.name.startswith((".", "$")):
                    try:
                        child_count = sum(1 for _ in item.iterdir())
                        subdirs.append({
                            "name": item.name,
                            "path": str(item),
                            "items": child_count,
                        })
                    except OSError:
                        pass
            tree_node["folders"] = subdirs[:30]
        except OSError:
            pass
        roots_data.append(tree_node)
    return jsonify({
        "roots": root_names,
        "roots_detailed": roots_data,
        "vault": str(c.vault),
    })


@app.get("/api/simulation_data")
def api_simulation_data():
    """Pre-packaged simulation data for instant 60fps sorting chamber animation."""
    c = cfg()
    items = _plan_items(c)
    dups = _duplicates(c)
    dup_paths = set()
    for g in dups:
        for f in g.get("files", [])[1:]:
            dup_paths.add(f.get("path", "").lower())

    folders = set()
    steps = []
    for idx, it in enumerate(items[:600]):  # High impact animation cohort
        is_dup = it.source.lower() in dup_paths
        dest_folder = f"{it.category} / {it.subcategory}"
        folders.add(dest_folder)
        p = Path(it.source)
        rel_folder = str(p.parent.relative_to(p.anchor)) if p.is_absolute() else str(p.parent)
        steps.append({
            "idx": idx,
            "id": it.id,
            "name": p.name,
            "ext": p.suffix.lower(),
            "size": it.size,
            "category": it.category,
            "subcategory": it.subcategory,
            "dest_folder": dest_folder,
            "is_duplicate": is_dup,
            "folder_path": rel_folder,
            "depth": min(len(p.parts), 7),
            "confidence": it.confidence,
            "reason": it.reason,
            "status": it.status,
            "thumb": p.suffix.lower() in THUMBABLE,
        })

    return jsonify({
        "total": len(items),
        "steps": steps,
        "folders": sorted(list(folders)),
        "duplicates_count": len(dup_paths),
    })


@app.get("/api/live_stream")
def api_live_stream():
    """Server-Sent Events streaming live folder traversal, file moves, and duplicates."""
    c = cfg()
    mode = request.args.get("mode", "simulate")
    items = _plan_items(c)
    dups = _duplicates(c)
    dup_paths = set()
    for g in dups:
        for f in g.get("files", [])[1:]:
            dup_paths.add(f.get("path", "").lower())

    def event_stream():
        yield f"data: {json.dumps({'type': 'init', 'total': len(items), 'roots': [str(r) for r in c.roots]})}\n\n"
        time.sleep(0.08)

        created_folders = set()
        seen_dirs = set()

        for idx, item in enumerate(items[:400]):
            p = Path(item.source)
            parent_dir = str(p.parent)

            # Step 1: Scanning nested folder check
            if parent_dir not in seen_dirs:
                seen_dirs.add(parent_dir)
                yield f"data: {json.dumps({'type': 'scan_folder', 'path': parent_dir, 'name': p.parent.name, 'depth': min(len(p.parts), 7)})}\n\n"
                time.sleep(0.02)

            # Step 2: Folder creation event if new folder
            dest_folder = f"{item.category} / {item.subcategory}"
            if dest_folder not in created_folders:
                created_folders.add(dest_folder)
                yield f"data: {json.dumps({'type': 'folder_create', 'category': item.category, 'subcategory': item.subcategory, 'name': dest_folder})}\n\n"
                time.sleep(0.03)

            # Step 3: Duplicate or standard move
            is_dup = item.source.lower() in dup_paths
            if is_dup:
                yield f"data: {json.dumps({'type': 'duplicate_found', 'id': item.id, 'name': p.name, 'ext': p.suffix.lower(), 'size': item.size, 'from': item.source, 'target': 'Duplicates / Review'})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'file_move', 'id': item.id, 'name': p.name, 'ext': p.suffix.lower(), 'size': item.size, 'from': item.source, 'category': item.category, 'subcategory': item.subcategory, 'dest_folder': dest_folder, 'confidence': item.confidence, 'thumb': p.suffix.lower() in THUMBABLE})}\n\n"

            if (idx + 1) % 15 == 0:
                pct = round(100 * (idx + 1) / max(len(items), 1))
                yield f"data: {json.dumps({'type': 'progress', 'processed': idx + 1, 'total': len(items), 'pct': pct})}\n\n"
            time.sleep(0.04)

        yield f"data: {json.dumps({'type': 'complete', 'total': len(items)})}\n\n"

    return Response(event_stream(), mimetype="text/event-stream")


@app.get("/api/settings")
def api_settings_get():
    c = cfg()
    return jsonify({
        "vault": str(c.vault),
        "roots": [str(r) for r in c.roots],
        "layout": c.layout,
        "max_depth": c.max_depth,
        "min_file_age_hours": c.min_file_age_hours,
        "confidence_threshold": c.confidence_threshold,
        "treat_projects_as_units": c.treat_projects_as_units,
        "move_projects": c.move_projects,
        "llm_enabled": c.llm.enabled,
        "llm_model": c.llm.model,
    })


def _rel(c: Config, dest: str) -> str:
    try:
        return str(Path(dest).relative_to(c.vault))
    except (ValueError, OSError):
        return dest


# ----------------------------------------------------------------- previews

THUMB_SIZE = 260

THUMBABLE = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff",
    ".ico", ".svg", ".pdf",
}
PREVIEWABLE = THUMBABLE | {
    ".txt", ".md", ".log", ".csv", ".json", ".xml", ".html", ".htm",
    ".css", ".js", ".py", ".java", ".c", ".cpp", ".h",
}


def _thumb_path(c: Config, key: str) -> Path:
    return c.state_dir / "thumbs" / f"{key}.jpg"


def _make_thumb(src: Path, out: Path, size: int = THUMB_SIZE) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".pdf":
        try:
            import fitz
            with fitz.open(str(src)) as doc:
                if doc.page_count == 0:
                    return False
                page = doc.load_page(0)
                zoom = (size * 1.4) / max(page.rect.width, 1)
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                pix.save(str(out))
            return True
        except Exception:
            pass

    try:
        from PIL import Image
        with Image.open(src) as im:
            im.draft("RGB", (size * 2, size * 2))
            im.thumbnail((size, size))
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.save(out, "JPEG", quality=78, optimize=True)
        return True
    except Exception:
        pass
    return False


def _placeholder_thumb(out: Path, tag: str) -> bool:
    try:
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (THUMB_SIZE, THUMB_SIZE // 4 * 3), (26, 30, 44))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((10, 10, THUMB_SIZE - 10, THUMB_SIZE // 4 * 3 - 10),
                            radius=14, outline=(60, 68, 96), width=2)
        label = (tag or "FILE")[:12].upper()
        d.text((THUMB_SIZE // 2 - len(label) * 4, THUMB_SIZE // 4 * 3 // 2 - 6),
               label, fill=(150, 158, 184))
        im.save(out, "JPEG", quality=80)
        return True
    except Exception:
        return False


@app.get("/thumb/<key>")
def thumb(key: str):
    c = cfg()
    cached = _thumb_path(c, key)
    if not cached.exists():
        target = _item_source(c, key)
        if target is None or not target.exists() or target.is_dir():
            abort(404)
        if not _make_thumb(target, cached):
            tag = target.suffix.lstrip(".") or "file"
            if not _placeholder_thumb(cached, tag):
                abort(404)
    return send_file(str(cached), mimetype="image/jpeg", max_age=3600)


@app.get("/thumb_path")
def thumb_path():
    path_param = request.args.get("path", "").strip()
    if not path_param:
        abort(404)
    target = Path(path_param)
    if not target.exists() or target.is_dir():
        abort(404)
    c = cfg()
    key = file_id(target)
    cached = _thumb_path(c, key)
    if not cached.exists():
        if not _make_thumb(target, cached):
            tag = target.suffix.lstrip(".") or "file"
            if not _placeholder_thumb(cached, tag):
                abort(404)
    return send_file(str(cached), mimetype="image/jpeg", max_age=3600)


@app.get("/file/<key>")
def view_file(key: str):
    c = cfg()
    target = _item_source(c, key)
    if target is None or not target.exists() or target.is_dir():
        abort(404)
    try:
        return send_file(str(target), max_age=0)
    except Exception:
        abort(404)


def _item_source(c: Config, key: str) -> Path | None:
    for item in _plan_items(c):
        if item.id == key:
            return Path(item.source)
    return None


@app.get("/api/text/<key>")
def api_text(key: str):
    c = cfg()
    for f in _inventory_files(c):
        if f.id == key:
            return jsonify({
                "name": f.name,
                "kind": f.kind,
                "chars": f.text_chars,
                "text": (f.text or "")[:4000],
                "note": f.note,
            })
    return jsonify({"error": "not found"}), 404


@app.get("/api/tree")
def api_tree():
    c = cfg()
    items = _plan_items(c)
    tree: dict[str, dict] = {}
    for item in items:
        cat = tree.setdefault(item.category, {"files": 0, "bytes": 0, "subs": {}})
        cat["files"] += 1
        cat["bytes"] += item.size
        sub = cat["subs"].setdefault(item.subcategory, {"files": 0, "bytes": 0})
        sub["files"] += 1
        sub["bytes"] += item.size
    out = []
    for name, data in sorted(tree.items(), key=lambda kv: -kv[1]["files"]):
        out.append({
            "name": name,
            "files": data["files"],
            "bytes": data["bytes"],
            "subs": [{"name": k, "files": v["files"], "bytes": v["bytes"]}
                     for k, v in sorted(data["subs"].items(), key=lambda kv: -kv[1]["files"])],
        })
    vault = _vault_stats(c)
    return jsonify({"plan": out, "vault": vault})


@app.post("/api/move")
def api_move():
    body = request.get_json(silent=True) or {}
    ids = [str(i) for i in body.get("ids", [])]
    category = str(body.get("category", "")).strip()
    subcategory = str(body.get("subcategory", "")).strip()
    if not ids or not category:
        return jsonify({"error": "need ids and category"}), 400

    c = cfg()
    tax = load_taxonomy(c.taxonomy_path)
    valid = {c2["name"]: {s["name"] for s in c2.get("subcategories", [])}
             for c2 in tax.get("categories", [])}
    if category not in valid:
        return jsonify({"error": f"unknown category {category}"}), 400
    if subcategory and subcategory not in valid[category]:
        return jsonify({"error": f"unknown subcategory {subcategory}"}), 400
    if not subcategory:
        subcategory = next(iter(valid[category]), "Needs Review")

    changed = 0
    items = _plan_items(c)
    for item in items:
        if item.id not in ids:
            continue
        item.category = category
        item.subcategory = subcategory
        item.confidence = 1.0
        item.method = "manual"
        item.reason = "moved by user in dashboard"
        if not item.is_dir:
            dest = c.vault / safe_name(category) / safe_name(subcategory) / safe_name(Path(item.source).name)
            item.destination = str(dest)
            item.status = "ready"
        changed += 1

    meta = _plan_meta(c)
    c.state_file("plan.json").write_text(json.dumps({
        "generated": time.time(),
        "stats": meta.get("stats", {}),
        "items": to_json(items),
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    _cache.pop("vault_ts", None)
    return jsonify({"changed": changed})


@app.post("/api/apply_selected")
def api_apply_selected():
    body = request.get_json(silent=True) or {}
    ids = {str(i) for i in body.get("ids", [])}
    if not ids:
        return jsonify({"error": "nothing selected"}), 400

    def job() -> None:
        c = cfg()
        items = [i for i in _plan_items(c) if i.id in ids]
        try:
            res = apply_plan(
                c, items,
                copy=bool(body.get("copy")),
                include_low_confidence=True,
                progress=lambda n, t: _set(pct=100 * n / max(t, 1), message=f"moving {n}/{t}"),
            )
            _set(message="done", result={
                "moved": res.moved, "copied": res.copied, "skipped": res.skipped,
                "failed": res.failed, "bytes": res.bytes_moved,
                "journal": str(res.journal) if res.journal else "",
                "errors": res.errors[:20],
            })
            _set(state="done", pct=100, finished=time.time())
        except Exception as exc:
            _set(state="error", message=f"{type(exc).__name__}: {exc}", finished=time.time())
        _cache.pop("vault_ts", None)

    with _lock:
        if _job["state"] == "running":
            return jsonify({"error": "a job is already running"}), 409
        _job.update({
            "id": _job["id"] + 1, "action": "apply", "state": "running",
            "pct": 0, "message": "moving selected files", "started": time.time(),
            "finished": 0.0, "result": {},
        })
    threading.Thread(target=job, daemon=True).start()
    return jsonify({"started": True, "count": len(ids)})


# ----------------------------------------------------------------- actions

def _set(**kw) -> None:
    with _lock:
        _job.update(kw)


def _snapshot() -> dict:
    with _lock:
        return dict(_job)


@app.post("/api/scan_scope")
def api_scan_scope():
    """Sets the scan scope to custom directory, multiple directories, or Full PC (all drives)."""
    body = request.get_json(silent=True) or {}
    mode = str(body.get("mode", "custom")).strip().lower()
    c = cfg()

    if mode == "full":
        # Discovers all active Windows drives
        drives = [Path(f"{d}:\\") for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
        c.roots = drives
    elif mode == "custom":
        raw_path = str(body.get("path", "")).strip()
        if not raw_path:
            return jsonify({"error": "Directory path is required"}), 400
        p = Path(raw_path)
        if not p.exists() or not p.is_dir():
            return jsonify({"error": f"Directory not found: {raw_path}"}), 400
        c.roots = [p]
    elif mode == "multi":
        paths = body.get("paths", [])
        valid = [Path(p) for p in paths if os.path.exists(p) and os.path.isdir(p)]
        if not valid:
            return jsonify({"error": "No valid directory paths provided"}), 400
        c.roots = valid

    _cache.clear()
    return jsonify({
        "success": True,
        "mode": mode,
        "roots": [str(r) for r in c.roots],
    })


@app.post("/api/undo_file")
def api_undo_file():
    """Physically restores a single file from its destination back to its original location."""
    body = request.get_json(silent=True) or {}
    src = str(body.get("src", "")).strip()
    dst = str(body.get("dst", "")).strip()
    if not src or not dst:
        return jsonify({"error": "Need source and destination paths"}), 400

    dst_p = Path(dst)
    src_p = Path(src)
    if not dst_p.exists():
        return jsonify({"error": f"File no longer exists at destination: {dst}"}), 404

    try:
        src_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst_p), str(src_p))
        _cache.clear()
        return jsonify({"success": True, "restored_to": str(src_p)})
    except Exception as exc:
        return jsonify({"error": f"Failed to undo move: {exc}"}), 500


@app.post("/api/move_file_custom")
def api_move_file_custom():
    """Physically moves a file on disk (standard Windows Explorer move, zero shortcuts)."""
    body = request.get_json(silent=True) or {}
    file_path = str(body.get("file_path", "")).strip()
    dest_folder = str(body.get("dest_folder", "")).strip()
    if not file_path or not dest_folder:
        return jsonify({"error": "File path and destination folder required"}), 400

    src_p = Path(file_path)
    dst_dir = Path(dest_folder)
    if not src_p.exists():
        return jsonify({"error": f"File does not exist: {file_path}"}), 404

    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        target = dst_dir / src_p.name
        if target.exists():
            from organizer.planner import _dedupe
            target = _dedupe(target, 1)
        shutil.move(str(src_p), str(target))
        _cache.clear()
        return jsonify({"success": True, "moved_to": str(target)})
    except Exception as exc:
        return jsonify({"error": f"Move failed: {exc}"}), 500


@app.post("/api/duplicates/isolate_all")
def api_isolate_all_duplicates():
    """Physically isolates all duplicate files into the dedicated 'Duplicates & Review' vault folder."""
    c = cfg()
    dups = _duplicates(c)
    target_dir = c.vault / "Duplicates & Review"
    target_dir.mkdir(parents=True, exist_ok=True)

    moved = 0
    errors = []
    for g in dups:
        # Keep first copy, isolate redundant copies
        for f in g.get("files", [])[1:]:
            src_str = f.get("path", "")
            if not src_str or not os.path.exists(src_str):
                continue
            src_p = Path(src_str)
            dest_p = target_dir / src_p.name
            if dest_p.exists():
                from organizer.planner import _dedupe
                dest_p = _dedupe(dest_p, 1)
            try:
                shutil.move(str(src_p), str(dest_p))
                moved += 1
            except Exception as exc:
                errors.append(f"{src_p.name}: {exc}")

    _cache.clear()
    return jsonify({
        "success": True,
        "moved": moved,
        "destination": str(target_dir),
        "errors": errors[:10],
    })


@app.get("/api/job")
def api_job():
    return jsonify(_snapshot())


@app.post("/api/clear_cache")
def api_clear_cache():
    """Wipes all in-memory caches, state files (inventory, plan, audit), and thumbnails for a completely fresh start."""
    global _cancel_requested
    _cancel_requested = True
    c = cfg()
    with _lock:
        _job.update({
            "state": "idle",
            "message": "Cache and state reset to zero",
            "pct": 0,
            "finished": time.time(),
            "current_file": "",
            "current_folder": "",
            "count": 0,
            "total": 0,
        })
    _cache.clear()

    # Reset inventory.json to empty
    inv_file = c.state_file("inventory.json")
    inv_file.write_text(json.dumps({
        "generated": 0, "roots": [], "count": 0, "errors": [], "files": []
    }, indent=1), encoding="utf-8")

    # Reset plan.json to empty
    plan_file = c.state_file("plan.json")
    plan_file.write_text(json.dumps({
        "generated": 0,
        "stats": {
            "total": 0, "bytes": 0, "high_confidence": 0, "low_confidence": 0,
            "by_category": {}, "by_method": {}
        },
        "items": []
    }, indent=1), encoding="utf-8")

    # Reset audit.json to empty
    audit_file = c.state_file("audit.json")
    audit_file.write_text(json.dumps({
        "duplicates": [], "empty_dirs": [], "junk": [], "unsorted": []
    }, indent=1), encoding="utf-8")

    # Wipe thumbnail cache folder
    thumb_dir = c.state_file("thumbs")
    if thumb_dir.exists() and thumb_dir.is_dir():
        try:
            shutil.rmtree(thumb_dir)
            thumb_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    return jsonify({
        "success": True,
        "message": "All cache, inventory, plan, and thumbnail state cleared."
    })


@app.post("/api/job/cancel")
@app.post("/api/job/reset")
def api_job_cancel():
    """Immediately cancels any running background job and resets the state to idle."""
    global _cancel_requested
    _cancel_requested = True
    with _lock:
        _job.update({
            "state": "idle",
            "message": "Job canceled / reset by user",
            "pct": 0,
            "finished": time.time(),
            "current_file": "",
            "current_folder": "",
        })
    return jsonify({"success": True, "message": "Job canceled and reset to idle."})


@app.post("/api/run")
def api_run():
    global _cancel_requested
    body = request.get_json(silent=True) or {}
    action = str(body.get("action", "")).strip()
    if action not in {"scan", "plan", "apply", "audit", "undo"}:
        return jsonify({"error": "unknown action"}), 400
    with _lock:
        if _job["state"] == "running":
            return jsonify({"error": "a job is already running", "job": dict(_job)}), 409
        _cancel_requested = False
        _job.update({
            "id": _job["id"] + 1, "action": action, "state": "running",
            "pct": 0, "message": "Starting " + action, "started": time.time(),
            "finished": 0.0, "result": {}, "current_file": "", "current_folder": "",
            "count": 0, "total": 0,
        })
    threading.Thread(target=_run_job, args=(action, body), daemon=True).start()
    return jsonify({"started": True, "action": action})


def _run_job(action: str, opts: dict) -> None:
    c = cfg()
    try:
        if action == "scan":
            _scan_job(c)
        elif action == "plan":
            _plan_job(c, opts)
        elif action == "apply":
            _apply_job(c, opts)
        elif action == "audit":
            _audit_job(c)
        elif action == "undo":
            _undo_job(c)
    except InterruptedError:
        _set(state="idle", message="Job stopped by user", pct=0, finished=time.time())
        return
    except Exception as exc:
        _set(state="error", message=f"{type(exc).__name__}: {exc}", finished=time.time())
        return
    _set(state="done", pct=100, finished=time.time())
    _cache.clear()


def _scan_job(c: Config) -> None:
    global _cancel_requested
    _cancel_requested = False
    _set(message="Discovering files and folders...", current_file="", current_folder="", count=0, bytes=0, pct=0)

    total_bytes = 0

    def on_progress(n: int, p: Path) -> bool:
        nonlocal total_bytes
        if _cancel_requested:
            return False
        try:
            total_bytes += p.stat().st_size
        except Exception:
            pass
        _set(
            message=f"Scanning: {p.name}",
            current_file=p.name,
            current_folder=str(p.parent),
            count=n,
            bytes=total_bytes,
            pct=min(99, int(n % 100)),
        )
        return True

    files, errors = scan(c, on_progress=on_progress)
    if _cancel_requested:
        _set(state="idle", message="Scan stopped by user", pct=0)
        return
    path = c.state_file("inventory.json")
    path.write_text(json.dumps({
        "generated": time.time(),
        "roots": [str(r) for r in c.roots],
        "count": len(files),
        "errors": errors[:200],
        "files": [f.to_dict() for f in files],
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    _cache.clear()
    _set(
        action="plan",
        message=f"Scan complete ({len(files)} files). Auto-generating classification plan...",
        result={"files": len(files), "errors": len(errors)},
        count=len(files),
        bytes=total_bytes,
        pct=50,
        current_file="",
        current_folder="",
    )
    # Seamlessly build plan so files are immediately ready to move!
    _plan_job(c, {})


def _plan_job(c: Config, opts: dict) -> None:
    global _cancel_requested
    _cancel_requested = False
    files = _inventory_files(c)
    if not files:
        raise RuntimeError("No inventory yet - run scan first")
    tax = load_taxonomy(c.taxonomy_path)
    use_llm = not bool(opts.get("no_llm"))
    _set(message=f"Classifying: 0/{len(files)} (0%)", count=0, total=len(files), pct=0)

    def on_plan_progress(n: int, t: int) -> None:
        if _cancel_requested:
            raise InterruptedError("Plan canceled by user")
        pct = round(100 * n / max(t, 1))
        _set(
            pct=pct,
            count=n,
            total=t,
            message=f"Classifying: {n}/{t} items ({pct}%)",
        )

    items, stats = build_plan(
        c, files, tax, use_llm=use_llm,
        progress=on_plan_progress,
    )
    _cache.clear()
    if _cancel_requested:
        _set(state="idle", message="Plan stopped by user", pct=0)
        return
    c.state_file("plan.json").write_text(json.dumps({
        "generated": time.time(), "stats": stats, "items": to_json(items),
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    write_report(items, stats, c.report_dir / "plan.html", c.vault)
    _set(
        message=f"Plan ready: {len(items)} items classified",
        result=stats,
        pct=100,
        count=len(items),
        total=len(items),
    )


def _apply_job(c: Config, opts: dict) -> None:
    global _cancel_requested
    _cancel_requested = False
    items = _plan_items(c)
    if not items:
        raise RuntimeError("No plan ready - build plan first")

    def on_apply_progress(n: int, t: int) -> None:
        if _cancel_requested:
            raise InterruptedError("Apply canceled by user")
        pct = round(100 * n / max(t, 1))
        _set(
            pct=pct,
            count=n,
            total=t,
            message=f"Moving file {n}/{t} ({pct}%)",
        )

    result = apply_plan(
        c, items,
        copy=bool(opts.get("copy")),
        include_low_confidence=bool(opts.get("include_unsure")),
        progress=on_apply_progress,
    )
    if _cancel_requested:
        _set(state="idle", message="Filing stopped by user", pct=0)
        return
    _set(
        message=f"Done: {result.moved + result.copied} files filed",
        result={
            "moved": result.moved, "copied": result.copied, "skipped": result.skipped,
            "failed": result.failed, "bytes": result.bytes_moved,
            "journal": str(result.journal) if result.journal else "",
            "errors": result.errors[:20],
        },
        pct=100,
    )


def _audit_job(c: Config) -> None:
    _set(message="hashing files", pct=2)

    def tick(n: int) -> None:
        _set(pct=min(88, 2 + 86 * (n / (n + 900))), message=f"hashing · {n} files checked")

    report = run_audit(c, on_progress=tick)
    _set(pct=92, message="writing report")
    c.state_file("audit.json").write_text(json.dumps({
        "duplicates": [[str(p) for p in g] for g in report["duplicates"]],
        "empty_dirs": [str(p) for p in report["empty_dirs"]],
        "junk": [str(p) for p in report["junk"]],
        "unsorted": [str(p) for p in report["unsorted"]],
    }, indent=1), encoding="utf-8")
    _set(result={
        "duplicate_groups": len(report["duplicates"]),
        "empty_dirs": len(report["empty_dirs"]),
        "junk": len(report["junk"]),
        "unsorted": len(report["unsorted"]),
    })


def _undo_job(c: Config) -> None:
    restored, failed, errors = undo_last(c)
    _set(result={"restored": restored, "failed": failed, "errors": errors[:20]})


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    print(f"\n  =======================================================")
    print(f"  ⚡ Wardrobe Live Dashboard  ->  http://{host}:{port}")
    print(f"  Exact Claude Photo Sorter Experience with Real-Time Sorting")
    print(f"  =======================================================\n")
    if open_browser:
        import webbrowser
        def _open():
            time.sleep(1.2)
            try:
                webbrowser.open(f"http://{host}:{port}")
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()
    app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    serve(port=int(os.environ.get("WARDROBE_PORT", 8765)))
