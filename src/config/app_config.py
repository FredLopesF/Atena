"""Load and save user preferences from downloader_config.json.

CONFIG_JSON_DATA is never written here — consoles live in consoles.json.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from src.core.constants import APP_VERSION, CONFIG_FILE

log = logging.getLogger(__name__)


def _path(app_dir: Path) -> Path:
    return app_dir / CONFIG_FILE


def load(app_dir: Path) -> dict[str, Any]:
    """Return user preferences dict.  Returns {} if file is missing or stale."""
    p = _path(app_dir)
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
        if data.get("config_version") != APP_VERSION:
            _backup(p)
            return {}
        data.pop("CONFIG_JSON_DATA", None)
        return data
    except (json.JSONDecodeError, OSError):
        log.warning("Config file corrupt or unreadable, backing up and resetting.")
        _backup(p)
        return {}


def save(app_dir: Path, config: dict[str, Any]) -> None:
    """Persist preferences.  CONFIG_JSON_DATA is stripped before writing."""
    clean = {k: v for k, v in config.items() if k != "CONFIG_JSON_DATA"}
    clean["config_version"] = APP_VERSION
    p = _path(app_dir)
    try:
        with p.open("w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2)
    except OSError as exc:
        raise OSError(f"Could not save config: {exc}") from exc


def _backup(path: Path) -> None:
    if path.exists():
        try:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            shutil.copy2(path, path.with_suffix(f".{stamp}.bak"))
        except OSError:
            log.warning("Failed to create config backup at '%s'", path)
