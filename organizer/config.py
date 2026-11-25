from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = APP_DIR / "state"
REPORT_DIR = APP_DIR / "reports"

DEFAULT_IGNORE_DIRS = {
    "appdata", "windows", "program files", "program files (x86)", "programdata",
    "$recycle.bin", "system volume information", "node_modules", "__pycache__",
    ".git", ".svn", ".hg", ".venv", "venv", "site-packages", ".cache", ".npm",
    ".nuget", ".gradle", ".m2", ".next", ".turbo", ".idea", "obj", "bin",
}

DEFAULT_IGNORE_EXTS = {
    ".tmp", ".temp", ".crdownload", ".part", ".partial", ".lock",
    ".dll", ".sys", ".drv", ".ocx", ".lnk", ".url", ".db-wal", ".db-shm",
}

DEFAULT_IGNORE_NAMES = {
    "desktop.ini", "thumbs.db", ".ds_store", "ntuser.dat", "bootmgr",
}

# A folder containing any of these is a project, not a pile of files.
DEFAULT_PROJECT_MARKERS = {
    ".git", ".hg", ".svn", "package.json", "pyproject.toml", "setup.py",
    "requirements.txt", "cargo.toml", "go.mod", "composer.json", "pom.xml",
    "build.gradle", "build.gradle.kts", "gemfile", "cmakelists.txt", "makefile",
    "deno.json", "bun.lockb", "pnpm-lock.yaml", "yarn.lock", "tsconfig.json",
    "vite.config.ts", "next.config.js", "nuxt.config.ts", "dockerfile",
    "docker-compose.yml", "remotion.config.ts", ".sln", ".csproj", ".xcodeproj",
    "mix.exs", "pubspec.yaml", "tauri.conf.json",
    # working sets that must stay together (render pipelines, dashboards)
    "index.csv", "manifest.json", "workspace.json", ".workspace",
}


@dataclass
class LlmConfig:
    enabled: str | bool = "auto"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    batch_size: int = 15
    timeout_seconds: int = 90
    temperature: float = 0.0

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "").strip()

    @property
    def usable(self) -> bool:
        if self.enabled is False or str(self.enabled).lower() == "false":
            return False
        if str(self.enabled).lower() == "auto":
            return bool(self.api_key)
        return bool(self.api_key) or "localhost" in self.base_url or "127.0.0.1" in self.base_url


@dataclass
class Config:
    app_dir: Path = APP_DIR
    vault: Path = Path.home() / "Organized"
    roots: list[Path] = field(default_factory=list)
    min_file_age_hours: float = 0.0
    max_size_mb: int = 512
    confidence_threshold: float = 0.55
    recursive: bool = True
    max_depth: int = 8
    layout: str = "{category}/{subcategory}/{filename}"
    people: list[str] = field(default_factory=list)
    ignore_dirs: set[str] = field(default_factory=lambda: set(DEFAULT_IGNORE_DIRS))
    ignore_exts: set[str] = field(default_factory=lambda: set(DEFAULT_IGNORE_EXTS))
    ignore_names: set[str] = field(default_factory=lambda: set(DEFAULT_IGNORE_NAMES))
    llm: LlmConfig = field(default_factory=LlmConfig)
    fallback: dict[str, list[str]] = field(default_factory=dict)
    treat_projects_as_units: bool = True
    move_projects: bool = False
    move_bundles: bool = True
    project_markers: set[str] = field(default_factory=lambda: set(DEFAULT_PROJECT_MARKERS))
    protected_paths: list[Path] = field(default_factory=list)
    taxonomy_path: Path = APP_DIR / "taxonomy.json"
    state_dir: Path = STATE_DIR
    report_dir: Path = REPORT_DIR

    # ---------- loading ----------

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Config":
        path = Path(path) if path else (APP_DIR / "config.toml")
        raw: dict = {}
        if path.exists():
            with path.open("rb") as fh:
                raw = tomllib.load(fh)

        general = raw.get("general", {})
        layout = raw.get("layout", {})
        ignore = raw.get("ignore", {})
        llm_raw = raw.get("llm", {})

        cfg = cls()
        cfg.app_dir = path.resolve().parent

        if general.get("vault"):
            cfg.vault = _expand(general["vault"], cfg.app_dir)
        cfg.roots = [_expand(r, cfg.app_dir) for r in general.get("roots", [])]
        cfg.min_file_age_hours = float(general.get("min_file_age_hours", 0))
        cfg.max_size_mb = int(general.get("max_size_mb", 512))
        cfg.confidence_threshold = float(general.get("confidence_threshold", 0.55))
        cfg.recursive = bool(general.get("recursive", True))
        cfg.max_depth = int(general.get("max_depth", 8))
        cfg.treat_projects_as_units = bool(general.get("treat_projects_as_units", True))
        cfg.move_projects = bool(general.get("move_projects", False))
        cfg.move_bundles = bool(general.get("move_bundles", True))
        if general.get("project_markers"):
            cfg.project_markers = {m.lower() for m in general["project_markers"]}
        if general.get("people"):
            cfg.people = [str(p).strip() for p in general["people"] if str(p).strip()]

        cfg.layout = layout.get("pattern", cfg.layout)

        if ignore.get("dirs"):
            cfg.ignore_dirs = {d.lower() for d in ignore["dirs"]}
        if ignore.get("extensions"):
            cfg.ignore_exts = {e.lower() for e in ignore["extensions"]}
        if ignore.get("names"):
            cfg.ignore_names = {n.lower() for n in ignore["names"]}
        # never ingest our own vault or our own program folder
        cfg.ignore_dirs.add(cfg.vault.name.lower())
        cfg.ignore_dirs.add(cfg.app_dir.name.lower())

        cfg.llm = LlmConfig(
            enabled=llm_raw.get("enabled", "auto"),
            base_url=str(llm_raw.get("base_url", "https://api.openai.com/v1")).rstrip("/"),
            model=str(llm_raw.get("model", "gpt-4o-mini")),
            api_key_env=str(llm_raw.get("api_key_env", "OPENAI_API_KEY")),
            batch_size=int(llm_raw.get("batch_size", 15)),
            timeout_seconds=int(llm_raw.get("timeout_seconds", 90)),
            temperature=float(llm_raw.get("temperature", 0)),
        )

        fb = raw.get("fallback", {})
        cfg.fallback = {str(k).lower(): list(v) for k, v in fb.items()}

        protect = raw.get("protect", {})
        cfg.protected_paths = [_expand(p, cfg.app_dir) for p in protect.get("paths", [])]

        # state and taxonomy live next to the config file that was used, so a
        # test config never writes into the real wardrobe's state.
        cfg.state_dir = cfg.app_dir / "state"
        cfg.report_dir = cfg.app_dir / "reports"

        local_tax = cfg.app_dir / "taxonomy.json"
        cfg.taxonomy_path = local_tax if local_tax.exists() else (APP_DIR / "taxonomy.json")
        return cfg

    # ---------- helpers ----------

    def ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def state_file(self, name: str) -> Path:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        return self.state_dir / name


def _expand(value: str, base: Path) -> Path:
    text = str(value)
    if text.startswith("@"):
        known = resolve_known_folder(text[1:])
        if known is not None:
            return known
    p = Path(os.path.expandvars(text)).expanduser()
    if not p.is_absolute():
        p = base / p
    return p.resolve()


# ---------------------------------------------------------------------------
# Windows shell folders. Desktop / Documents / Pictures are often redirected
# into OneDrive, so a hardcoded "C:/Users/me/Desktop" is simply wrong.
# ---------------------------------------------------------------------------

_KNOWN_ALIASES = {
    "desktop": "Desktop",
    "documents": "Personal",
    "pictures": "My Pictures",
    "music": "My Music",
    "videos": "My Video",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "onedrive": "OneDrive",
}

_KNOWN_FALLBACK = {
    "desktop": "Desktop",
    "documents": "Documents",
    "pictures": "Pictures",
    "music": "Music",
    "videos": "Videos",
    "downloads": "Downloads",
    "onedrive": "OneDrive",
}


def resolve_known_folder(alias: str) -> Path | None:
    alias = alias.strip().lower()
    reg_name = _KNOWN_ALIASES.get(alias)
    if reg_name and os.name == "nt":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                raw, _ = winreg.QueryValueEx(key, reg_name)
            p = Path(os.path.expandvars(raw))
            if p.exists():
                return p.resolve()
        except OSError:
            pass

    fallback = _KNOWN_FALLBACK.get(alias)
    if fallback:
        p = Path.home() / fallback
        if p.exists():
            return p.resolve()
        od = Path.home() / "OneDrive" / fallback
        if od.exists():
            return od.resolve()
    return None


def load_taxonomy(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_taxonomy(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def category_names(tax: dict) -> list[str]:
    return [c["name"] for c in tax.get("categories", [])]


def find_category(tax: dict, name: str) -> dict | None:
    lname = name.strip().lower()
    for c in tax.get("categories", []):
        if c["name"].strip().lower() == lname:
            return c
    return None
