# Wardrobe

A semantic file organiser for Windows. It reads your files, works out what each
one is **for**, and files it into a folder structure that makes sense to a human
— not `PDF/`, `Images/`, `2024/`.

The core rule: **the AI only labels. Deterministic code moves.** You review a
plan before anything is touched, and every move is journaled and reversible.

---

## Quick start

### 🚀 1-Click Launch (Windows)
Simply double-click **`start.bat`** (or `./start.sh` on Linux/macOS).
It checks your Python environment, installs any missing packages from `requirements.txt`, launches the live dashboard on `http://127.0.0.1:8765`, and opens your default browser automatically.

### 💻 Command Line
```bat
organize.cmd scan        :: read every file, build an inventory
organize.cmd plan        :: classify -> plan.json + a visual review board
organize.cmd apply       :: execute (asks you to type "yes")
organize.cmd status      :: what's in the wardrobe now
organize.cmd watch       :: keep filing new arrivals, hands off
organize.cmd dashboard   :: the live web dashboard (recommended)
```

**The dashboard** is the nicest way to use this. `organize.cmd dashboard` opens
`http://127.0.0.1:8765` — a live control room showing every file, where it is
going, what was held back and why, duplicate waste, and a feed of every move.
Buttons for Scan / Plan / Apply / Find duplicates / Undo, with a progress bar
per job. It reads the same state files as the CLI, is bound to localhost only,
and never invents a number.

`plan` writes `reports\plan.html` — open it in a browser. That's the review
board: every file, its destination, a confidence score and the reason it was
placed there. Nothing moves until you run `apply`.

---

## Commands

| Command | What it does |
|---|---|
| `scan` | Walks your roots, extracts text from docx/xlsx/pptx/pdf/txt/code, saves `state\inventory.json` |
| `taxonomy` | Prints the current wardrobe categories |
| `plan` | Classifies everything, writes `state\plan.json` + `reports\plan.html` |
| `apply` | Moves files. `--copy` to leave originals, `--include-unsure` for low confidence |
| `undo` | Reverses the most recent `apply`, file by file |
| `audit` | Finds duplicates, empty folders, junk and leftovers |
| `status` | Size and file count per category |
| `watch` | Loops: files new arrivals above a confidence bar, logs every action |
| `dashboard` | Live web dashboard: every file, every decision, every duplicate |

Useful flags:

```bat
organize.cmd plan --limit 40              :: try it on 40 files first
organize.cmd plan --no-llm                :: rules engine only, no API call
organize.cmd apply --copy                 :: originals stay put
organize.cmd apply -y                     :: skip the confirmation prompt
organize.cmd watch --once                 :: one pass, for Task Scheduler
organize.cmd watch --interval 300         :: check every 5 minutes
organize.cmd watch --min-confidence 0.9   :: only the obvious ones
```

---

## How classification works

Two engines, layered:

**1. Rules engine** (`organizer/rules.py`) — always on, no internet, no key.
Scores each category against keywords found in the filename, the folder path and
the first pages of the file. Matching is token-based, so `sdk` does not match
`asdkjhqwe` and `notes` does not outvote `call notes`. Weighted: filename hit >
path hit > body hit — and body text is capped, so a word buried inside a file can
only ever *suggest* a category, never silently decide one.

**1b. Image reading** (`organizer/media.py`) — no vision model needed.
For photos, the words inside the file are useless, so this reads the pixels and
metadata instead: width/height, aspect ratio, EXIF camera make/model, capture
date, and the filename. That is enough to tell a phone photo from a screenshot
from an OEM wallpaper — which is what decides the folder. `2022_Acer_OLED_
3840x2400.jpg` is recognised as *artwork*, `Screenshot 2024-03-01.png` as a
*screenshot*, and `IMG_3301.jpg` as a real photo. No `.jpg` dumping ground.

**1c. OCR** (`organizer/ocr.py`) — reads paper, not just filenames.
Scanned PDFs, photos of bills, screenshots of a chat: none of these have text to
extract, so before this they were invisible and guessed by name. Now:
- images that aren't obviously camera photos or artwork are OCR'd with tesseract;
- a PDF with no selectable text layer is rendered page by page and OCR'd;
- text found this way is marked `scan`/`document` and fed to the classifier.

Verified on a generated image-only invoice PDF: it read `TAX INVOICE`,
`Rs 18,500` and `Due Date: 15-04-2024` with no text layer in the file at all.
Tesseract is optional: without it everything still runs, PDFs just fall back to
their filename. Install it with `winget install UB-Mannheim.TesseractOCR`.

**2. LLM** (`organizer/llm.py`) — kicks in automatically if an API key exists.
Sends batches of `{filename, folder, kind, excerpt}` and asks for one label each.

Any OpenAI-compatible endpoint works. Easiest local option, free and private:

```bat
winget install Ollama.Ollama
ollama pull qwen2.5:7b
```

```toml
[llm]
enabled = true
base_url = "http://localhost:11434/v1"
model = "qwen2.5:7b"
api_key_env = "OLLAMA_KEY"   # set any dummy value
```

Or a hosted model:

```toml
[llm]
enabled = true
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
api_key_env = "OPENAI_API_KEY"    # setx OPENAI_API_KEY sk-...
```

If the LLM errors, times out or returns garbage, those files fall back to rules.
The run never fails because of the network.

**Anything below `confidence_threshold` goes to `Unsorted/Needs Review`** instead
of being guessed into a real category. That folder is your work queue — move a
file out, add a keyword to `taxonomy.json`, and it stops happening.

---

## The wardrobe

`taxonomy.json` is the whole brain. Ten categories, each with subcategories,
keywords and optional file extensions:

```
Money & Paperwork      Taxes · Invoices & Receipts · Banking · Insurance · Loans · Salary
Work & Clients         Clients · Contracts · Deliverables · Meetings · Pitches
Code & Development     Projects · Configs · Databases · API Docs · Scripts
Creative Projects      YouTube & Shorts · Editing · Design & Brand · Audio · Ideas
Learning & Reference   Courses · Books · Papers · Guides · Notes
Personal & Life        Identity · Health · Home & Bills · Travel · Family
Media Library          Photos · Screenshots · Wallpapers & Art · Personal Video · Music
Installers & Software  Installers · Drivers · Licences
Archive & Old          Old Versions · Zips & Bundles
Unsorted               Needs Review
```

Edit it freely. Add a category for your own life (`Guitar`, `Cooking`,
`Freelance — Acme Corp`), add keywords, re-run `plan`. That is how the wardrobe
becomes *yours* instead of a generic template.

Layout inside the vault is a template in `config.toml`:

```toml
[layout]
pattern = "{category}/{subcategory}/{filename}"
```

`{year}` and `{month}` are available too — but the default deliberately doesn't
use them, because date folders hide everything.

---

## Three things that protect you from a second mess

### 1. Project folders are units, not files

A folder containing `.git`, `package.json`, `pyproject.toml`, `Cargo.toml`,
`index.csv` or similar is a **project**. It is treated as one object. The
organiser never walks inside and never files its 4,000 files individually —
that would destroy the repo.

By default project folders are classified but **left where they are**
(`move_projects = false`), because moving a repo breaks absolute paths,
virtualenvs and IDE settings.

### 2. `[protect]` — the off-limits list

Active workspaces, render pipelines and app resource folders go here:

```toml
[protect]
paths = [
  "C:/Users/you/Downloads/New YT",
  "C:/Users/you/Videos/Clipper Engine",
  "C:/Users/you/OneDrive/Documents/CyberLink",
]
```

Anything under these paths is invisible to the organiser: not read, not listed,
not moved. This is the escape hatch that keeps a good wardrobe from eating your
tools.

### 3. Real shell folders, not guesses

Desktop, Documents and Pictures are usually redirected into OneDrive. A
hardcoded `C:/Users/you/Desktop` is then the wrong, empty folder. Roots use
`@` aliases resolved from the Windows registry:

```toml
roots = ["@downloads", "@desktop", "@documents", "@pictures", "@videos", "@music"]
```

---

## Safety

- **Nothing is deleted. Ever.** Not by any command.
- `apply` verifies the file still exists and hasn't changed size since `scan`.
- It never overwrites: name collisions become `report (2).pdf`.
- Every move is written to `state\undo-<timestamp>.json` (last 40 kept).
- `undo` refuses to clobber a file that reappeared at the original path.
- Junctions, symlinks and reparse points are never followed (no infinite loops,
  no duplicate copies of the same folder).
- OneDrive cloud placeholders are detected and **not** downloaded just to be
  classified.
- System paths, `AppData`, `node_modules`, `.git`, `Program Files`, hidden
  folders, the vault itself and this program's own folder are skipped.
- `~$` Office lock files, `desktop.ini`, `Thumbs.db`, `.crdownload` and other
  in-progress junk are skipped.
- Low-confidence files are not moved by default.
- `watch` only auto-files at `--min-confidence` (default 80%) and logs every
  decision to `state\watch.log`.

Recommended first run: `plan`, look at the HTML board, then `apply --copy`.

---

## Performance notes

- Text extraction is pure stdlib: `.docx/.xlsx/.pptx` are read straight out of
  their zip containers, no python-docx needed.
- `.pdf` is the one exception. Without `pypdf` installed, PDFs are classified by
  filename and folder only. To get real PDF text:
  ```bat
  pip install pypdf
  ```
  (Already installed in this workspace — verified on a real salary slip, 1,273
  characters extracted, correctly filed under Salary & Employment.)
- Files over `max_size_mb` are classified by name only, never opened.
- A 12,000-file Downloads folder scans in about a second, because project
  folders collapse to one entry each.
- `audit` hashes every file — it's the slow one. Everything else is fast.

---

## Files

```
config.toml            roots, vault, layout, protect list, ignore rules, LLM
taxonomy.json          the categories - this is the wardrobe
organize.py            CLI entry point
organize.cmd           Windows wrapper (so you don't need to type "python")
organizer/
  config.py            config + taxonomy loading, @shell-folder resolution
  scanner.py           walks roots, detects projects, builds FileInfo records
  textract.py          text out of docx/xlsx/pptx/pdf/txt/code, zero deps
  media.py             reads pixels + EXIF to tell photos from screenshots/art
  ocr.py               tesseract OCR for images and scanned PDFs
  rules.py             deterministic token-based scorer
  llm.py               OpenAI-compatible batch classifier
  planner.py           builds the move plan, handles collisions and protection
  apply.py             executes + journals + undo
  report.py            the HTML review board
  audit.py             duplicates, empty dirs, junk
dashboard/
  app.py               Flask server: the live view + job runner
  templates/index.html the dashboard page
  static/style.css     its styling and animations
  static/app.js        its logic
tests/
  test_rules.py        regression tests for the classifier
  test_media.py        image provenance tests
  test_ocr.py          OCR tests against real rendered text
state/                 inventory.json, plan.json, undo journals, seen.json, watch.log
reports/               plan.html
```

---

## Roadmap (not built yet)

- **Semantic dedupe** — find the *same document* re-saved as PDF and DOCX.
- **Learning from corrections** — when you move a file out of `Unsorted`, record
  the keywords that would have caught it.
- **Two-way sync with Paperless-ngx** for the document-heavy half.
- **Local embeddings** — `sentence-transformers` for classification that never
  leaves the machine and costs nothing per file.
- **Scheduled runs** — wrap `watch --once` in a Windows Task Scheduler job.
- **Vision model** — ask a local llava model "what is this photo of?" for images
  where EXIF and filename are not enough.

---

## Prior art

Nothing does exactly this. Closest things:

- [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) — OCR + ML
  tagging, but a Docker web app that copies files into its own database.
- [organize-tool](https://github.com/tfeldmann/organize) — excellent rule engine
  (`if name contains …`), zero understanding.
- [FileBot](https://www.filebot.net/) — media only, metadata-driven.
- [TagSpaces](https://www.tagspaces.org/) — tagging UI, manual.
- Various `ai-file-organizer` repos — let the model move files directly, no
  review step, no journal, no taxonomy.
