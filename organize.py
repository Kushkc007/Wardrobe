"""Wardrobe - semantic file organiser.

    python organize.py scan       # read every file, build inventory
    python organize.py plan       # classify -> plan + HTML review board
    python organize.py apply      # execute the plan (journaled, undoable)
    python organize.py undo       # put everything back
    python organize.py audit      # duplicates, empty folders, leftovers
    python organize.py status     # what is in the wardrobe right now
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from organizer.apply import apply_plan, undo_last
from organizer.audit import run_audit
from organizer.config import (
    APP_DIR, Config, load_taxonomy,
)
from organizer.planner import PlanItem, build_plan, to_json
from organizer.report import human, write_report
from organizer.scanner import FileInfo, scan

BANNER = "Wardrobe"


# ----------------------------------------------------------------- helpers

def c(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def ok(t): return c(t, "32")
def warn(t): return c(t, "33")
def bad(t): return c(t, "31")
def dim(t): return c(t, "90")
def bold(t): return c(t, "1")


def bar(done: int, total: int, label: str = "") -> None:
    if not sys.stdout.isatty():
        return
    width = 28
    filled = int(width * done / max(total, 1))
    pct = 100 * done / max(total, 1)
    sys.stdout.write(f"\r  {label:<22} [{'#' * filled}{'.' * (width - filled)}] {pct:3.0f}%")
    if done >= total:
        sys.stdout.write("\n")
    sys.stdout.flush()


def save_inventory(cfg: Config, files: list[FileInfo], errors: list[str]) -> Path:
    path = cfg.state_file("inventory.json")
    payload = {
        "generated": time.time(),
        "roots": [str(r) for r in cfg.roots],
        "count": len(files),
        "errors": errors[:200],
        "files": [f.to_dict() for f in files],
    }
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def load_inventory(cfg: Config) -> list[FileInfo]:
    path = cfg.state_file("inventory.json")
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        data = json.loads(text)
        return [FileInfo(**f) for f in data.get("files", [])]
    except Exception:
        return []


def load_plan(cfg: Config) -> list[PlanItem]:
    path = cfg.state_file("plan.json")
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [PlanItem(**i) for i in data.get("items", [])]


def save_plan(cfg: Config, items: list[PlanItem], stats: dict) -> Path:
    path = cfg.state_file("plan.json")
    path.write_text(
        json.dumps({"generated": time.time(), "stats": stats, "items": to_json(items)},
                   indent=1, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


# ----------------------------------------------------------------- commands

def cmd_scan(cfg: Config, args) -> int:
    print(f"\n{bold('Scanning')} {len(cfg.roots)} root folders")
    for r in cfg.roots:
        mark = ok("ok") if r.exists() else bad("missing")
        print(f"  {dim('[' + mark + ']')} {r}")

    files, errors = scan(cfg, on_progress=lambda n, p: bar(n, n, "reading files"))
    if sys.stdout.isatty():
        sys.stdout.write("\n")
    path = save_inventory(cfg, files, errors)
    total = sum(f.size for f in files)
    print(f"\n  {bold(str(len(files)))} files, {human(total)} read")
    print(f"  with readable text: {sum(1 for f in files if f.text_chars > 50)}")
    if errors:
        print(f"  {warn(str(len(errors)) + ' skipped/errors')} (see {path.name})")
    print(f"  inventory -> {dim(str(path))}\n")
    return 0


def cmd_taxonomy(cfg: Config, args) -> int:
    tax = load_taxonomy(cfg.taxonomy_path)
    print(f"\n{bold('Taxonomy')} - {len(tax['categories'])} categories\n")
    for cat in tax["categories"]:
        subs = " | ".join(s["name"] for s in cat["subcategories"])
        print(f"  {bold(cat['name'])}")
        print(f"    {dim(subs)}")
    print(f"\n  edit {dim(str(cfg.taxonomy_path))} to change the wardrobe, then re-run plan.\n")
    return 0


def cmd_plan(cfg: Config, args) -> int:
    files = load_inventory(cfg)
    if not files:
        print(bad("\n  No inventory. Run:  organize.cmd scan\n"))
        return 1

    tax = load_taxonomy(cfg.taxonomy_path)
    if args.limit:
        files = files[: args.limit]

    use_llm = not args.no_llm
    if use_llm and cfg.llm.usable:
        print(f"\n{bold('Classifying')} {len(files)} files with {cfg.llm.model}")
    else:
        reason = "--no-llm" if args.no_llm else f"no key in ${cfg.llm.api_key_env}"
        print(f"\n{bold('Classifying')} {len(files)} files with the rules engine ({dim(reason)})")

    items, stats = build_plan(
        cfg, files, tax, use_llm=use_llm, progress=lambda n, t: bar(n, t, "classifying")
    )
    if sys.stdout.isatty():
        sys.stdout.write("\n")

    if stats["llm_error"]:
        print(warn(f"  AI error, fell back to rules: {stats['llm_error'][:160]}"))

    save_plan(cfg, items, stats)
    report_path = cfg.report_dir / "plan.html"
    write_report(items, stats, report_path, cfg.vault)

    print(f"\n  {bold(str(stats['total']))} files -> {len({i.category for i in items})} categories")
    print(f"  by AI: {stats['llm_labeled']}   by rules: {stats['rules_labeled']}")
    people_detected = {i.person for i in items if getattr(i, "person", "")}
    if people_detected:
        print(f"  {bold('People / Family detected:')} {ok(', '.join(sorted(people_detected)))}")
    junk_count = sum(1 for i in items if i.category == "WhatsApp Junk")
    if junk_count:
        print(f"  {ok(str(junk_count) + ' WhatsApp junk/greetings isolated')} into WhatsApp_Junk/")
    if stats["low_confidence"]:
        print(f"  {warn(str(stats['low_confidence']) + ' need review')} (sent to Unsorted/Needs Review)")
    if stats["protected"]:
        print(f"  {dim(str(stats['protected']) + ' project folders kept in place')}")
    if stats["conflicts"]:
        print(f"  {warn(str(stats['conflicts']) + ' name conflicts')} (auto-renamed)")

    print(f"\n  {bold('Review board:')} {dim(str(report_path))}")
    print(f"  Plan:         {dim(str(cfg.state_file('plan.json')))}")
    print(f"\n  Nothing has moved yet. When happy:\n    {bold('organize.cmd apply')}\n")
    return 0


def cmd_apply(cfg: Config, args) -> int:
    items = load_plan(cfg)
    if not items:
        print(bad("\n  No plan. Run:  organize.cmd plan\n"))
        return 1

    ready = [i for i in items if i.status not in {"low_confidence", "protected"}]
    low = sum(1 for i in items if i.status == "low_confidence")
    protected = sum(1 for i in items if i.status == "protected")
    print(f"\n{bold('Apply')} - {len(ready)} moves -> {cfg.vault}")
    if low:
        print(dim(f"  {low} low-confidence files stay in place unless --include-unsure"))
    if protected:
        print(dim(f"  {protected} project folders stay in place (move_projects = false)"))
    if args.copy:
        print(dim("  copy mode: originals are left where they are"))

    if not args.yes:
        try:
            answer = input(f"\n  Type {bold('yes')} to proceed: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  cancelled\n")
            return 1
        if answer not in {"yes", "y"}:
            print("  cancelled\n")
            return 1

    result = apply_plan(
        cfg,
        items,
        copy=args.copy,
        include_low_confidence=args.include_unsure,
        progress=lambda n, t: bar(n, t, "moving"),
    )
    if sys.stdout.isatty():
        sys.stdout.write("\n")

    verb = "copied" if args.copy else "moved"
    print(f"\n  {ok(str(result.copied or result.moved) + ' ' + verb)} | {human(result.bytes_moved)}")
    if result.skipped:
        print(f"  {warn(str(result.skipped) + ' skipped')}")
    if result.failed:
        print(f"  {bad(str(result.failed) + ' failed')}")
    for err in result.errors[:12]:
        print(f"    {dim(err)}")
    print(f"\n  Undo any time:  {bold('organize.cmd undo')}")
    print(f"  Journal: {dim(str(result.journal))}\n")
    return 0


def cmd_undo(cfg: Config, args) -> int:
    restored, failed, errors = undo_last(cfg)
    if not restored and not failed:
        print(warn("\n  " + (errors[0] if errors else "nothing to undo") + "\n"))
        return 1
    print(f"\n  {ok(str(restored) + ' files restored')}")
    if failed:
        print(f"  {warn(str(failed) + ' could not be restored')}")
    for err in errors[:10]:
        print(f"    {dim(err)}")
    print()
    return 0


def cmd_audit(cfg: Config, args) -> int:
    print(f"\n{bold('Audit')} - this can take a minute on large folders")
    report = run_audit(cfg)

    dups = report["duplicates"]
    wasted = sum(g[0].stat().st_size * (len(g) - 1) for g in dups)
    print(f"\n  Duplicates: {bold(str(len(dups)))} groups, {human(wasted)} recoverable")
    for group in dups[:8]:
        size = human(group[0].stat().st_size)
        print(f"    {dim(size):>10}  {group[0].name}")
        for extra in group[1:]:
            print(f"              {dim(str(extra))}")

    empties = report["empty_dirs"]
    print(f"\n  Empty folders: {bold(str(len(empties)))}")
    for p in empties[:8]:
        print(f"    {dim(str(p))}")

    junk = report["junk"]
    print(f"\n  Junk/partial downloads: {bold(str(len(junk)))}")

    unsorted_files = report["unsorted"]
    print(f"\n  Waiting in Unsorted/Needs Review: {bold(str(len(unsorted_files)))}")
    for p in unsorted_files[:10]:
        print(f"    {p.name}")

    out = cfg.state_file("audit.json")
    out.write_text(
        json.dumps(
            {
                "duplicates": [[str(p) for p in g] for g in dups],
                "empty_dirs": [str(p) for p in empties],
                "junk": [str(p) for p in junk],
                "unsorted": [str(p) for p in unsorted_files],
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\n  Detail -> {dim(str(out))}\n")
    return 0


def cmd_status(cfg: Config, args) -> int:
    print(f"\n{bold('Wardrobe status')}")
    print(f"  vault: {cfg.vault}  {'(missing)' if not cfg.vault.exists() else ''}")
    if cfg.vault.exists():
        rows = []
        for d in sorted(cfg.vault.iterdir()):
            if not d.is_dir():
                continue
            count = size = 0
            for p in d.rglob("*"):
                try:
                    if p.is_file():
                        count += 1
                        size += p.stat().st_size
                except OSError:
                    pass
            rows.append((d.name, count, size))
        for name, count, size in sorted(rows, key=lambda r: -r[1]):
            print(f"    {bold(f'{count:>5}')}  {human(size):>9}   {name}")
        print(f"    {dim(f'{sum(r[1] for r in rows):>5}  {human(sum(r[2] for r in rows)):>9}   total')}")

    inv = cfg.state_file("inventory.json")
    plan = cfg.state_file("plan.json")
    print(f"\n  inventory: {dim('yes' if inv.exists() else 'not yet')}")
    print(f"  plan:      {dim('yes' if plan.exists() else 'not yet')}")
    print(f"  AI:        {dim(cfg.llm.model if cfg.llm.usable else 'off (rules only)')}")
    print()
    return 0


def cmd_watch(cfg: Config, args) -> int:
    """Keep the wardrobe tidy: file new arrivals, hands off, on a loop."""
    tax = load_taxonomy(cfg.taxonomy_path)
    seen_path = cfg.state_file("seen.json")
    seen: set[str] = set()
    if seen_path.exists():
        try:
            seen = set(json.loads(seen_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            seen = set()

    log_path = cfg.state_file("watch.log")
    settle = args.settle_minutes * 60
    print(f"\n{bold('Watching')} every {args.interval}s  "
          f"(confidence >= {args.min_confidence:.0%}, settle {args.settle_minutes}m)")
    print(f"  log -> {dim(str(log_path))}")
    print(dim("  Ctrl+C to stop\n"))

    while True:
        try:
            files, _errors = scan(cfg)
            now = time.time()
            fresh = [
                f for f in files
                if f.id not in seen and (now - f.mtime) >= settle
            ]
            if fresh:
                items, stats = build_plan(cfg, fresh, tax, use_llm=not args.no_llm)
                ready = [
                    i for i in items
                    if i.status == "ready" and i.confidence >= args.min_confidence
                ]
                skipped = len(items) - len(ready)
                line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  seen={len(fresh)} moved={len(ready)} held={skipped}"
                if ready:
                    res = apply_plan(cfg, ready)
                    line += f" failed={res.failed} bytes={res.bytes_moved}"
                print("  " + line)
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                seen.update(f.id for f in fresh)
                if len(seen) > 50_000:
                    seen = set(list(seen)[-40_000:])
                seen_path.write_text(json.dumps(sorted(seen)), encoding="utf-8")
            elif args.once:
                print("  nothing new")

            if args.once:
                return 0
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n  stopped\n")
            return 0


def cmd_dashboard(cfg: Config, args) -> int:
    """Serve the live dashboard on localhost."""
    sys.path.insert(0, str(APP_DIR))
    # The dashboard is a separate Flask process/import; pass the active config
    # through so `organize.py --config custom.toml dashboard` uses it too.
    config_path = getattr(cfg, "config_path", None)
    if config_path:
        import os
        os.environ["WARDROBE_CONFIG"] = str(config_path)
    from dashboard.app import serve

    open_browser = not getattr(args, "no_open", False)
    serve(host=args.host, port=args.port, open_browser=open_browser)
    return 0


# ----------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    if argv is None and len(sys.argv) <= 1:
        argv = ["dashboard"]

    parser = argparse.ArgumentParser(
        prog="organize", description="Wardrobe - a semantic file organiser"
    )
    parser.add_argument("--config", default=None, help="path to config.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="read every file and build an inventory")
    sub.add_parser("taxonomy", help="show the wardrobe categories")
    p_plan = sub.add_parser("plan", help="classify files and build a move plan")
    p_plan.add_argument("--no-llm", action="store_true", help="rules engine only")
    p_plan.add_argument("--limit", type=int, default=0, help="only plan the first N files")

    p_apply = sub.add_parser("apply", help="execute the plan")
    p_apply.add_argument("--yes", "-y", action="store_true", help="skip confirmation")
    p_apply.add_argument("--copy", action="store_true", help="copy instead of move")
    p_apply.add_argument("--include-unsure", action="store_true",
                         help="also move low-confidence files")

    sub.add_parser("undo", help="restore the last apply")
    sub.add_parser("audit", help="find duplicates, empty folders and junk")
    sub.add_parser("status", help="show what is in the wardrobe")

    p_watch = sub.add_parser("watch", help="keep filing new arrivals on a loop")
    p_watch.add_argument("--interval", type=int, default=600, help="seconds between passes")
    p_watch.add_argument("--settle-minutes", type=int, default=3,
                         help="only touch files older than this")
    p_watch.add_argument("--min-confidence", type=float, default=0.8,
                         help="auto-file only above this confidence")
    p_watch.add_argument("--once", action="store_true", help="single pass, then exit")
    p_watch.add_argument("--no-llm", action="store_true", help="rules engine only")

    p_dash = sub.add_parser("dashboard", help="open the live dashboard in a browser")
    p_dash.add_argument("--port", type=int, default=8765, help="port to serve on")
    p_dash.add_argument("--host", default="127.0.0.1", help="bind address (localhost only)")
    p_dash.add_argument("--no-open", action="store_true", help="do not open browser automatically")

    args = parser.parse_args(argv)
    cfg = Config.load(args.config)
    cfg.ensure_dirs()

    handlers = {
        "scan": cmd_scan,
        "taxonomy": cmd_taxonomy,
        "plan": cmd_plan,
        "apply": cmd_apply,
        "undo": cmd_undo,
        "audit": cmd_audit,
        "status": cmd_status,
        "watch": cmd_watch,
        "dashboard": cmd_dashboard,
    }
    try:
        return handlers[args.command](cfg, args)
    except KeyboardInterrupt:
        print("\n  interrupted\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())
