# ⚡ Wardrobe — Intelligent Semantic File Organizer & Live Control Room

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()
[![Offline Safe](https://img.shields.io/badge/privacy-100%25%20Offline%20First-success.svg)]()

> **A human-centric, deterministic file organizer with a real-time web dashboard.**  
> It reads your messy folders, understands what each file is **actually for**, and organizes everything into meaningful categories (e.g. `Money & Paperwork/Invoices & Receipts`, `Work & Clients/Contracts`, `Personal & Life/Identity`) — instead of useless dumping grounds like `PDF/`, `Images/`, or `2024/`.

<br/>

<div align="center">
  <img src="assets/wardrobe_demo.gif" alt="Wardrobe Live Dashboard Demo" width="100%" />
  <p><em>Real-Time Live Sorting Chamber and Interactive Move Validation Control Room</em></p>
</div>

---

## 📑 Table of Contents

1. [What is Wardrobe? (Project Overview)](#-what-is-wardrobe)
2. [How It Works (Under the Hood)](#-how-it-works)
3. [Quick Start & Launch Options](#-quick-start)
   - [Option A: Standalone .EXE (No Python Needed)](#option-a-standalone-executable-wardrobeexe)
   - [Option B: 1-Click Launcher (Windows `start.bat`)](#option-b-1-click-launcher-startbat)
   - [Option C: Command Line Interface](#option-c-command-line-interface)
4. [How & Where to Connect (Configuration Guide)](#-how--where-to-connect-configuration-guide)
   - [1. 100% Offline Mode (Default — No Keys Required)](#1-100-offline-mode-default--no-keys-needed)
   - [2. Connecting Local AI (Ollama / LM Studio)](#2-connecting-local-ai-ollama--lm-studio)
   - [3. Connecting Cloud AI (OpenAI / Groq / OpenRouter)](#3-connecting-cloud-ai-openai--groq--openrouter)
   - [4. Setting Source Folders & Destination Vault](#4-setting-source-folders--destination-vault)
   - [5. Protecting Active Projects & Folders](#5-protecting-active-projects--workspaces)
   - [6. Separating Family / Team Documents](#6-separating-family--team-member-documents)
5. [The Live Dashboard Control Room](#-the-live-dashboard-control-room)
6. [The Wardrobe Brain (`taxonomy.json`)](#-the-wardrobe-brain-taxonomyjson)
7. [Guaranteed Safety & Rollback](#-guaranteed-safety--rollback)
8. [Building from Source](#-building-the-standalone-exe)

---

## 🧐 What is Wardrobe?

Most file organizers dump files by extension (`.pdf`, `.jpg`) or modification date. That doesn't solve clutter — it just creates a second organized mess. 

**Wardrobe is different:**
- **Understands Content:** It extracts embedded text from PDFs, Word docs (`.docx`), Excel sheets (`.xlsx`), PowerPoint decks (`.pptx`), and plain text/code.
- **Understands Images:** It reads EXIF metadata, aspect ratios, and resolution to separate genuine camera photos from screenshots, memes, and wallpapers without needing heavy vision models.
- **Reads Scanned Paper:** Integrates with Tesseract OCR to read text inside scanned physical invoices and paper receipts.
- **Deterministic & Safe:** The AI/classifier only suggests labels. Real file movements are handled by strict, verified Python code with automatic name-collision protection (`invoice (2).pdf`) and an atomic rollback journal.
- **Never Deletes:** Wardrobe **never** deletes your original files.

---

## ⚙️ How It Works

```
                               ┌────────────────────────────────────────────────┐
                               │             Source Folders (Roots)             │
                               │  (@downloads, @desktop, @documents, custom)    │
                               └───────────────────────┬────────────────────────┘
                                                       │
                                            Fast Recursive Scanner
                                       (Detects & Preserves Git Repos)
                                                       │
                                ┌──────────────────────┴──────────────────────┐
                                ▼                                             ▼
                     Embedded Text Extractor                        Media Provenance Analyzer
                   (PyMuPDF / docx / xlsx / txt)                     (EXIF, aspect ratio, dims)
                                │                                             │
                                └──────────────────────┬──────────────────────┘
                                                       │
                                            Two-Tier Classification
                                                       │
                       ┌───────────────────────────────┴───────────────────────────────┐
                       ▼                                                               ▼
             Tier 1: Rules Engine (Default)                               Tier 2: Optional LLM
         - 100% offline, zero latency                                 - Ollama (Local) or OpenAI/Groq
         - Token-based weighted scoring                               - Triggered only when enabled
         - Provenance & kinship detection                             - Auto-fallback to rules on error
                       │                                                               │
                       └───────────────────────────────┬───────────────────────────────┘
                                                       │
                                        Move Validation & Staging
                                 (User reviews & unchecks unwanted moves)
                                                       │
                                    Safe Execution & Transaction Journal
                                        Destination: ~/Organized
```

---

## 🚀 Quick Start

Choose whichever launch option fits your style:

### Option A: Standalone Executable (`Wardrobe.exe`)
*Best for users who want zero installations or do not have Python installed.*
1. Go to the `dist/` folder (or download `Wardrobe.exe` from Releases).
2. Double-click **`Wardrobe.exe`**.
3. It immediately starts the local server and opens your web browser to `http://127.0.0.1:8765`.

### Option B: 1-Click Launcher (`start.bat`)
*Best for Windows users running from the source repo.*
1. Double-click **`start.bat`** in the project folder.
2. It automatically checks Python, installs missing packages from `requirements.txt`, launches the dashboard, and pops open your browser.
*(On macOS / Linux, run `./start.sh`)*

### Option C: Command Line Interface
*Best for terminal power users and automated scripts.*
```bat
organize.cmd scan        :: Scan roots and generate inventory
organize.cmd plan        :: Classify files and generate plan.json + review board
organize.cmd apply       :: Move files to their destination vault
organize.cmd undo        :: Instantly reverse the last move operation
organize.cmd audit       :: Find duplicate files and empty directories
organize.cmd watch       :: Background watcher that files new arrivals automatically
organize.cmd dashboard   :: Start the interactive web dashboard on localhost
```

---

## 🔌 How & Where to Connect (Configuration Guide)

All settings are controlled by **`config.toml`**. You can edit it with any text editor (Notepad, VS Code, etc.).

### 1. 100% Offline Mode (Default — No Keys Needed)
By default, Wardrobe runs completely offline using its built-in rule engine:
```toml
[llm]
enabled = false # or "auto" without an API key
```
- **No API keys needed.**
- **No internet required.**
- Analyzes filenames, folder paths, document headers, and media metadata deterministically.

---

### 2. Connecting Local AI (Ollama / LM Studio)
If you want deep semantic classification without your data leaving your computer:

1. Install [Ollama](https://ollama.com/) and pull a lightweight model:
   ```bash
   ollama pull qwen2.5:7b
   ```
2. In `config.toml`, configure the `[llm]` section:
   ```toml
   [llm]
   enabled = true
   base_url = "http://localhost:11434/v1"
   model = "qwen2.5:7b"
   api_key_env = "OLLAMA_API_KEY" # Any dummy value works
   ```
Wardrobe will now query your local Ollama instance over localhost!

---

### 3. Connecting Cloud AI (OpenAI / Groq / OpenRouter)
If you prefer hosted models for ultra-high accuracy on difficult documents:

1. Get an API key from [OpenAI](https://platform.openai.com/), [Groq](https://groq.com/), or [OpenRouter](https://openrouter.ai/).
2. Set your environment variable in Windows:
   ```cmd
   setx OPENAI_API_KEY "sk-your-actual-api-key"
   ```
3. In `config.toml`:
   ```toml
   [llm]
   enabled = "auto" # Will activate automatically when key is detected
   base_url = "https://api.openai.com/v1" # Or https://api.groq.com/openai/v1
   model = "gpt-4o-mini" # Or llama-3.3-70b-versatile
   api_key_env = "OPENAI_API_KEY"
   ```

---

### 4. Setting Source Folders & Destination Vault

Open `config.toml`:
```toml
[general]
# Where sorted files will be organized
vault = "~/Organized"

# Folders to scan and organize.
# "@name" resolves real Windows shell paths (including OneDrive-redirected folders)
roots = [
  "@downloads",
  "@desktop",
  "@documents",
  "@pictures",
  "@videos",
  "@music",
  # "D:/MyCustomFolder" # You can add explicit paths too
]
```

---

### 5. Protecting Active Projects & Workspaces
Wardrobe has built-in project awareness:
- Any folder containing `.git`, `package.json`, `pyproject.toml`, `Cargo.toml`, etc., is recognized as a **Project Unit** and will **never** be dismantled into loose files.
- To keep specific workspaces completely off-limits, add them to `[protect]`:
```toml
[protect]
paths = [
  "~/Downloads/ActiveWork",
  "~/Videos/RawFootage",
]
```

---

### 6. Separating Family / Team Member Documents
If multiple people share the computer, Wardrobe can automatically identify their personal files (resumes, medical reports, salary slips, IDs) and organize them into separate subfolders:
```toml
[general]
people = ["Alex", "Jordan", "Sam"]
```
Files matching these names will land under `Personal & Life/Identity/<Name>` or `Money & Paperwork/Salary/<Name>`.

---

## 🎛️ The Live Dashboard Control Room

Running `start.bat` or `Wardrobe.exe` opens the web control room at **`http://127.0.0.1:8765`**:

1. **⚡ Live Sorting Chamber:** An animated hopper with live speed controls (1x, 2x, 5x, Max) where you watch incoming files glide into dynamically generated category folders.
2. **📁 File Explorer & Validation Staging:** 
   - View every file with its destination, preview thumbnail, and confidence score.
   - **Interactive Checkboxes:** All planned files are selected by default. Simply uncheck any file you wish to keep in place, then click **`[ 🚀 Move Allowed Files ]`**.
3. **⧉ Duplicates & Review Station:** Identifies duplicate copies across different folders using cryptographic hashes, allowing 1-click duplicate isolation.
4. **↺ Changes & Rollback Journal:** Complete audit trail of every file moved, with instant 1-click restoration.

---

## 🧠 The Wardrobe Brain (`taxonomy.json`)

The default taxonomy is organized into 10 intuitive human domains:

| Category | Primary Subcategories |
|---|---|
| **Money & Paperwork** | Taxes, Invoices & Receipts, Banking, Insurance, Salary, Loans |
| **Work & Clients** | Clients, Contracts, Deliverables, Meetings, Pitches & Decks |
| **Personal & Life** | Identity & Certificates, Health & Medical, Home & Bills, Travel |
| **Learning & Reference** | Courses, Books & Ebooks, Research Papers, Guides, Notes |
| **Media Library** | Camera Photos, Screenshots, Wallpapers, Personal Videos, Music |
| **Code & Development** | Repositories, Configs & Env, Databases, Scripts, Documentation |
| **Creative Projects** | Video Editing, YouTube & Shorts, Graphic Design, Audio Assets |
| **Installers & Software** | Software Installers, Drivers, License Keys |
| **Archive & Old** | Old Versions, Zip Bundles |
| **Unsorted** | Needs Review (Safety buffer for ambiguous files) |

You can customize categories, subcategories, and keywords at any time by editing `taxonomy.json`.

---

## 🛡️ Guaranteed Safety & Rollback

- **No Overwriting:** If `Report.pdf` already exists in the destination, Wardrobe names the new file `Report (2).pdf`.
- **Atomic Journaling:** Every move is recorded in `state/undo-<timestamp>.json`. Running `organize.cmd undo` or clicking **Undo** in the dashboard reverses the move file-by-file.
- **Project Preservation:** Software repositories and complex projects are never taken apart.
- **Zero Cloud Uploads by Default:** Operates strictly on localhost (`127.0.0.1`).

---

## 📦 Standalone Portable Executable

A pre-compiled standalone **`Wardrobe.exe`** (requiring zero setup or Python installation) is available for direct download under the [Releases](https://github.com/Kushkc007/Wardrobe/releases) tab. Simply download and double-click to run!

---

## 📄 License

This project is licensed under the [MIT License](LICENSE). Feel free to use, modify, and distribute it freely.
