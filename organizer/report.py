"""A single self-contained HTML page so you can review the wardrobe before it exists."""
from __future__ import annotations

import html
import time
from collections import defaultdict
from pathlib import Path

from .planner import PlanItem

CSS = """
:root{--bg:#0f1115;--card:#171a21;--line:#262b36;--fg:#e6e9ef;--dim:#8b93a7;
--ok:#4ade80;--warn:#fbbf24;--bad:#f87171;--accent:#7c9cff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}
header{padding:28px 32px 18px;border-bottom:1px solid var(--line);
position:sticky;top:0;background:rgba(15,17,21,.92);backdrop-filter:blur(8px);z-index:5}
h1{margin:0 0 4px;font-size:20px;letter-spacing:-.02em}
.sub{color:var(--dim);font-size:13px}
.stats{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:9px;
padding:7px 12px;font-size:12px;color:var(--dim)}
.stat b{color:var(--fg);font-size:14px;margin-right:5px}
main{padding:22px 32px 80px;max-width:1500px}
#q{width:100%;max-width:420px;margin:18px 0 6px;padding:10px 13px;border-radius:9px;
border:1px solid var(--line);background:var(--card);color:var(--fg);font-size:13px;outline:none}
#q:focus{border-color:var(--accent)}
.cat{margin-top:26px;border:1px solid var(--line);border-radius:13px;overflow:hidden;background:var(--card)}
.cat h2{margin:0;padding:13px 16px;font-size:14px;letter-spacing:.01em;
background:#1b1f28;border-bottom:1px solid var(--line);display:flex;justify-content:space-between}
.cat h2 span{color:var(--dim);font-weight:400;font-size:12px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
td{padding:8px 16px;border-bottom:1px solid rgba(38,43,54,.55);vertical-align:top}
tr:last-child td{border-bottom:0}
tr:hover td{background:#1d2230}
.fn{font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;font-size:12px;
word-break:break-all;color:#dfe4ee}
.meta{color:var(--dim);font-size:11.5px;margin-top:2px}
.pill{display:inline-block;padding:1px 8px;border-radius:20px;font-size:11px;
font-weight:600;white-space:nowrap}
.hi{background:rgba(74,222,128,.14);color:var(--ok)}
.mid{background:rgba(251,191,36,.14);color:var(--warn)}
.lo{background:rgba(248,113,113,.14);color:var(--bad)}
.tag{background:#222838;color:var(--dim);border-radius:5px;padding:1px 6px;font-size:10.5px}
.dest{color:var(--accent);font-family:ui-monospace,Consolas,monospace;font-size:11.5px}
.empty{color:var(--dim);padding:22px 0}
"""

JS = """
const q=document.getElementById('q');
q.addEventListener('input',()=>{
  const v=q.value.toLowerCase();
  document.querySelectorAll('tr[data-s]').forEach(tr=>{
    tr.style.display = tr.dataset.s.includes(v) ? '' : 'none';
  });
  document.querySelectorAll('.cat').forEach(c=>{
    const rows=[...c.querySelectorAll('tr[data-s]')];
    c.style.display = rows.some(r=>r.style.display!=='none') ? '' : 'none';
  });
});
"""


def write_report(items: list[PlanItem], stats: dict, out: Path, vault: Path) -> Path:
    grouped: dict[str, dict[str, list[PlanItem]]] = defaultdict(lambda: defaultdict(list))
    for it in items:
        grouped[it.category][it.subcategory].append(it)

    order = sorted(grouped.items(), key=lambda kv: -len(sum(kv[1].values(), [])))

    parts: list[str] = []
    for cat, subs in order:
        total = sum(len(v) for v in subs.values())
        size = sum(i.size for v in subs.values() for i in v)
        parts.append(f'<section class="cat"><h2>{esc(cat)}<span>{total} files · {human(size)}</span></h2><table>')
        for sub, files in sorted(subs.items(), key=lambda kv: -len(kv[1])):
            files_sorted = sorted(files, key=lambda x: x.source.lower())
            parts.append(
                f'<tr><td colspan="2" style="padding:9px 16px;background:#151922;'
                f'color:var(--dim);font-size:11.5px;letter-spacing:.04em;'
                f'text-transform:uppercase">{esc(sub)} · {len(files_sorted)}</td></tr>'
            )
            for it in files_sorted:
                cls = "hi" if it.confidence >= 0.75 else "mid" if it.confidence >= 0.5 else "lo"
                search = f"{it.source} {it.category} {it.subcategory} {it.reason}".lower()
                if it.status == "protected":
                    dest_html = (
                        '<div class="dest" style="color:#8b93a7">stays where it is '
                        '(project folder)</div>'
                    )
                else:
                    dest_html = f'<div class="dest">→ {esc(rel(vault, it.destination))}</div>'
                kind = ""
                if it.is_dir:
                    kind = '<span class="tag">folder</span> '
                person_badge = f'<span class="tag" style="background:#26354a;color:#93c5fd;font-weight:600">👤 {esc(it.person)}</span> ' if getattr(it, "person", "") else ""
                parts.append(
                    f'<tr data-s="{esc_attr(search)}">'
                    f'<td style="width:58%"><div class="fn">{esc(Path(it.source).name)}</div>'
                    f'<div class="meta">{esc(str(Path(it.source).parent))}</div></td>'
                    f'<td>{dest_html}'
                    f'<div class="meta"><span class="pill {cls}">{it.confidence:.0%}</span> '
                    f'{person_badge}{kind}<span class="tag">{esc(it.method)}</span> {esc(it.reason)}</div></td></tr>'
                )
        parts.append("</table></section>")

    body = "".join(parts) or '<p class="empty">Nothing to show.</p>'

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Wardrobe plan · {len(items)} files</title>
<style>{CSS}</style></head><body>
<header>
  <h1>Wardrobe — proposed plan</h1>
  <div class="sub">Nothing has been moved. Review, then run <code>organize.cmd apply</code>.</div>
  <div class="stats">
    <div class="stat"><b>{stats.get('total', 0)}</b>files</div>
    <div class="stat"><b>{human(stats.get('bytes', 0))}</b>total</div>
    <div class="stat"><b>{stats.get('llm_labeled', 0)}</b>by AI</div>
    <div class="stat"><b>{stats.get('rules_labeled', 0)}</b>by rules</div>
    <div class="stat"><b>{stats.get('low_confidence', 0)}</b>needs review</div>
    <div class="stat"><b>{stats.get('conflicts', 0)}</b>name conflicts</div>
    <div class="stat"><b>{stats.get('protected', 0)}</b>project folders kept</div>
    <div class="stat">generated {time.strftime('%d %b %Y, %H:%M')}</div>
  </div>
  <input id="q" placeholder="Filter by name, folder, category or reason…">
</header>
<main>{body}</main>
<script>{JS}</script>
</body></html>"""

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return out


def esc(text) -> str:
    return html.escape(str(text), quote=False)


def esc_attr(text) -> str:
    return html.escape(str(text), quote=True)


def rel(vault: Path, dest: str) -> str:
    try:
        return str(Path(dest).relative_to(vault))
    except ValueError:
        return dest


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
