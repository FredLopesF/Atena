"""Cache service — stores game lists as JSON files under cache/."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from src.core.constants import CACHE_EXPIRY_DAYS
from src.core.models import GameFile
from src.core.utils import sanitize_filename

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get(cache_dir: Path, console_name: str) -> list[GameFile] | None:
    """Return cached games if they exist and have not expired, else None."""
    path = _cache_file(cache_dir, console_name)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        age_days = (time.time() - data.get("cached_at", 0)) / 86_400
        if age_days >= CACHE_EXPIRY_DAYS:
            return None
        return [GameFile(filename=g[0], size_str=g[1], size_bytes=g[2] if len(g) > 2 else 0) for g in data["games"]]
    except (json.JSONDecodeError, KeyError, OSError):
        log.warning("Corrupt or unreadable cache for '%s'", console_name)
        return None


def put(cache_dir: Path, console_name: str, games: list[GameFile]) -> None:
    """Write *games* to the cache, overwriting any existing entry."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_file(cache_dir, console_name)
    raw = {
        "cached_at": time.time(),
        "games": [[g.filename, g.size_str, g.size_bytes] for g in games],
    }
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(raw, f)
    except OSError:
        log.exception("Failed to write cache for '%s'", console_name)


def invalidate(cache_dir: Path, console_name: str) -> None:
    """Delete the cache file for *console_name* if it exists."""
    _cache_file(cache_dir, console_name).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cache_file(cache_dir: Path, console_name: str) -> Path:
    return cache_dir / f"{sanitize_filename(console_name)}.json"
