"""Housekeeping: duplicates, empty folders, junk, leftovers.

Every walk here honours the same rules the scanner does. The audit used to
rglob the whole tree, which meant "find duplicates" would read 191,000 files
inside a folder the user had explicitly protected. That is both slow and
disrespectful of the [protect] list - fixed by walking through _walk().
"""
from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from pathlib import Path

from .config import Config
from .scanner import _project_markers, _walk, is_protected

CHUNK = 1 << 20


def hash_file(path: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            while chunk := fh.read(CHUNK):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _iter_files(root: Path, cfg: Config):
    """Files under root, skipping protected paths, ignored dirs and projects."""
    if not root.exists() or is_protected(root, cfg):
        return
    for path, is_dir in _walk(root, cfg):
        if is_dir:
            # a project folder is one unit; do not hash its innards
            continue
        yield path


def find_duplicates(root: Path, cfg: Config, min_size: int = 512,
                    on_progress=None) -> list[list[Path]]:
    by_size: dict[int, list[Path]] = defaultdict(list)
    seen = 0
    for p in _iter_files(root, cfg):
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_size >= min_size:
            by_size[st.st_size].append(p)
        seen += 1
        if on_progress and seen % 200 == 0:
            on_progress(seen)

    # only sizes that occur more than once can possibly be duplicates
    candidates = {s: ps for s, ps in by_size.items() if len(ps) > 1}

    groups: list[list[Path]] = []
    for size, paths in candidates.items():
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for p in paths:
            digest = hash_file(p)
            if digest:
                by_hash[digest].append(p)
        groups.extend(v for v in by_hash.values() if len(v) > 1)
    return sorted(groups, key=lambda g: -g[0].stat().st_size)


def _iter_dirs(root: Path, cfg: Config):
    """Every real subdirectory under root, still honouring protection rules."""
    if not root.exists() or is_protected(root, cfg):
        return
    seen: set[str] = set()
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            real = str(Path(current).resolve()).lower()
        except OSError:
            continue
        if real in seen:
            continue
        seen.add(real)
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                if getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400:
                    continue  # junction / symlink
                if entry.name.lower() in cfg.ignore_dirs or entry.name.startswith("."):
                    continue
                child = Path(entry.path)
                if is_protected(child, cfg):
                    continue
                if depth + 1 > cfg.max_depth:
                    continue
                yield child
                if cfg.treat_projects_as_units and _project_markers(child, cfg):
                    continue  # do not walk into a repo
                stack.append((child, depth + 1))
            except OSError:
                continue


def empty_dirs(root: Path, cfg: Config) -> list[Path]:
    found = []
    dirs = list(_iter_dirs(root, cfg))
    for p in sorted(dirs, key=lambda x: -len(x.parts)):
        try:
            if not any(p.iterdir()):
                found.append(p)
        except OSError:
            continue
    return found


def run_audit(cfg: Config, on_progress=None) -> dict:
    report: dict = {"duplicates": [], "empty_dirs": [], "unsorted": [], "junk": []}

    # the vault is ours to tidy, but roots are the user's - respect [protect]
    for root in [cfg.vault] + cfg.roots:
        if not root.exists():
            continue
        report["duplicates"].extend(find_duplicates(root, cfg, on_progress=on_progress))
        report["empty_dirs"].extend(empty_dirs(root, cfg))

    unsorted_dir = cfg.vault / "Unsorted" / "Needs Review"
    if unsorted_dir.exists():
        report["unsorted"] = sorted(
            (p for p in unsorted_dir.rglob("*") if p.is_file()),
            key=lambda p: -p.stat().st_size,
        )

    junk_ext = {".tmp", ".crdownload", ".part", ".partial", ".bak"}
    for root in cfg.roots:
        for p in _iter_files(root, cfg):
            if p.suffix.lower() in junk_ext:
                report["junk"].append(p)
    return report
