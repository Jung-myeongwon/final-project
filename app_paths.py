"""Development and PyInstaller frozen-build path helpers."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_ENV_LOADED = False


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_base_dir() -> Path:
    """Writable directory (project root in dev, folder containing the exe when frozen)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundle_dir() -> Path:
    """Read-only bundled resources (PyInstaller _MEIPASS or project root in dev)."""
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def resolve_env_path() -> Path | None:
    """Return the first existing .env path (handles .env.txt on Windows)."""
    base = app_base_dir()
    for name in (".env", ".env.txt"):
        path = base / name
        if path.is_file():
            return path
    return None


def _parse_env_file(path: Path) -> None:
    """Fallback parser when python-dotenv misses UTF-16 / BOM / odd encodings."""
    text = None
    for encoding in ("utf-8-sig", "utf-8", "cp949", "utf-16", "utf-16-le"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if not text:
        return

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ[key] = value


def load_app_env() -> Path | None:
    """Load .env from the folder next to TasteLab.exe (or project root in dev)."""
    global _ENV_LOADED
    env_path = resolve_env_path()
    if env_path is None:
        return None

    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=True, encoding="utf-8")
    except Exception:
        pass

    _parse_env_file(env_path)
    _ENV_LOADED = True
    return env_path


def get_lastfm_api_key() -> str:
    if not _ENV_LOADED:
        load_app_env()
    return (os.environ.get("LASTFM_API_KEY") or "").strip()


def get_tmdb_api_key() -> str:
    if not _ENV_LOADED:
        load_app_env()
    return (os.environ.get("TMDB_API_KEY") or "").strip()


def ensure_data_files() -> None:
    """Copy movies.db next to the exe on first run so the DB stays writable."""
    db_dest = app_base_dir() / "data" / "movies.db"
    if db_dest.exists():
        return
    db_src = bundle_dir() / "data" / "movies.db"
    if not db_src.exists():
        return
    db_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(db_src, db_dest)


def ensure_env_file() -> None:
    """Create .env beside the exe from .env.example when missing."""
    if resolve_env_path() is not None:
        return
    env_dest = app_base_dir() / ".env"
    for name in (".env.example",):
        src = bundle_dir() / name
        if src.exists():
            shutil.copy2(src, env_dest)
            return
    env_dest.write_text(
        "# API keys\n"
        "LASTFM_API_KEY=\n"
        "TMDB_API_KEY=\n"
        "OMDB_API_KEY=\n",
        encoding="utf-8",
    )
