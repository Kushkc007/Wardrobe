"""Execute a plan, safely. Every move is journaled and reversible."""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .planner import PlanItem


@dataclass
class MoveResult:
    moved: int = 0
    skipped: int = 0
    failed: int = 0
    copied: int = 0
    bytes_moved: int = 0
    errors: list[str] = None
    journal: Path | None = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def apply_plan(
    cfg: Config,
    items: list[PlanItem],
    copy: bool = False,
    include_low_confidence: bool = False,
    progress=None,
) -> MoveResult:
    cfg.ensure_dirs()
    res = MoveResult()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    journal_path = cfg.state_file(f"undo-{stamp}.json")

    records: list[dict] = []
    actionable = [
        i for i in items
        if i.status != "protected"
        and (include_low_confidence or i.status != "low_confidence")
    ]

    for idx, item in enumerate(actionable):
        src = Path(item.source)
        dst = Path(item.destination)
        try:
            if not src.exists():
                res.skipped += 1
                res.errors.append(f"missing source: {src}")
                continue
            st = src.stat()
            if not item.is_dir and st.st_size != item.size:
                res.skipped += 1
                res.errors.append(f"size changed, left alone: {src}")
                continue
            if dst.exists():
                res.skipped += 1
                res.errors.append(f"destination exists, left alone: {dst}")
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)
            if copy:
                if src.is_dir():
                    shutil.copytree(str(src), str(dst), dirs_exist_ok=False)
                else:
                    shutil.copy2(src, dst)
                res.copied += 1
            else:
                shutil.move(str(src), str(dst))
                res.moved += 1
            res.bytes_moved += item.size
            records.append(
                {
                    "op": "copy" if copy else "move",
                    "src": str(src),
                    "dst": str(dst),
                    "ts": time.time(),
                }
            )
        except Exception as exc:
            res.failed += 1
            res.errors.append(f"{src}: {exc}")
        if progress:
            progress(idx + 1, len(actionable))

    journal_path.write_text(
        json.dumps({"created": time.time(), "records": records}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    res.journal = journal_path
    _prune_journals(cfg, keep=40)
    return res


def undo_last(cfg: Config, journal: Path | None = None) -> tuple[int, int, list[str]]:
    """Move everything from the newest journal back. Returns (restored, failed, errors)."""
    if journal is None:
        journals = sorted(cfg.state_file(".").glob("undo-*.json"))
        if not journals:
            return 0, 0, ["no journal found - nothing to undo"]
        journal = journals[-1]

    data = json.loads(journal.read_text(encoding="utf-8"))
    records = [r for r in data.get("records", []) if r.get("op") == "move"]
    restored = failed = 0
    errors: list[str] = []

    for rec in reversed(records):
        src, dst = Path(rec["src"]), Path(rec["dst"])
        try:
            if not dst.exists():
                errors.append(f"already gone: {dst}")
                failed += 1
                continue
            if src.exists():
                errors.append(f"original path occupied, not overwriting: {src}")
                failed += 1
                continue
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(src))
            restored += 1
        except Exception as exc:
            failed += 1
            errors.append(f"{dst}: {exc}")
    return restored, failed, errors


def _prune_journals(cfg: Config, keep: int) -> None:
    journals = sorted(cfg.state_file(".").glob("undo-*.json"))
    for old in journals[:-keep]:
        try:
            old.unlink()
        except OSError:
            pass
