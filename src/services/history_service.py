"""History service — tracks successfully downloaded files per console."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from src.core.utils import sanitize_filename

log = logging.getLogger(__name__)
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load(db_dir: Path, console_name: str) -> set[str]:
    """Return the set of filenames already downloaded for *console_name*."""
    path = _history_file(db_dir, console_name)
    if not path.exists():
        return set()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("downloaded_files", []))
    except (json.JSONDecodeError, OSError):
        log.warning("Corrupt or unreadable history file for '%s'", console_name)
        return set()


def record(db_dir: Path, console_name: str, filename: str) -> None:
    """Append *filename* to the history for *console_name* (thread-safe)."""
    db_dir.mkdir(parents=True, exist_ok=True)
    path = _history_file(db_dir, console_name)
    with _lock:
        try:
            data = {"downloaded_files": []}
            if path.exists():
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            if filename not in data["downloaded_files"]:
                data["downloaded_files"].append(filename)
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except (json.JSONDecodeError, OSError):
            log.exception("Failed to record '%s' in history for '%s'", filename, console_name)


def clear(db_dir: Path, console_name: str) -> None:
    """Delete the history file for *console_name* (thread-safe)."""
    path = _history_file(db_dir, console_name)
    with _lock:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _history_file(db_dir: Path, console_name: str) -> Path:
    return db_dir / f"{sanitize_filename(console_name)}.json"
