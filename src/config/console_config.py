"""Load and save console definitions from consoles.json.

On first run (consoles.json absent) the legacy CONFIG_JSON_DATA entries
from downloader_config.json are silently migrated and the key is removed
from that file.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.core.constants import CONFIG_FILE, CONSOLES_FILE
from src.core import credential_store
from src.core.models import Console

log = logging.getLogger(__name__)


def _path(app_dir: Path) -> Path:
    return app_dir / CONSOLES_FILE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load(app_dir: Path) -> dict[str, Console]:
    """Return {name: Console} mapping.

    Creates consoles.json via migration if it does not exist yet.
    """
    p = _path(app_dir)
    if not p.exists():
        raw = _migrate(app_dir)
        _write(p, raw)
        return _parse(raw)
    try:
        with p.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        return _parse(raw)
    except (json.JSONDecodeError, OSError):
        log.warning("Console config corrupt or unreadable at '%s'", p)
        return {}


def save(app_dir: Path, consoles: dict[str, Console]) -> None:
    """Persist the full console map to consoles.json.

    Credentials are stored in the OS keyring, not in the JSON file.
    """
    for name, c in consoles.items():
        if c.auth_email and c.auth_password:
            credential_store.save(name, c.auth_email, c.auth_password)
    raw = {name: _to_dict(c) for name, c in consoles.items()}
    _write(_path(app_dir), raw)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse(raw: dict[str, Any]) -> dict[str, Console]:
    result: dict[str, Console] = {}
    for name, cfg in raw.items():
        if not isinstance(cfg, dict):
            continue
        email, password = credential_store.load(name)
        result[name] = Console(
            name=name,
            type=cfg.get("type", "direct_url"),
            identifier=cfg.get("identifier"),
            url=cfg.get("url"),
            extensions=cfg.get("extensions", []),
            path=cfg.get("path"),
            auth_email=email,
            auth_password=password,
        )
    return result


def _to_dict(c: Console) -> dict[str, Any]:
    data: dict[str, Any] = {"type": c.type}
    if c.identifier:
        data["identifier"] = c.identifier
    if c.url:
        data["url"] = c.url
    if c.extensions:
        data["extensions"] = c.extensions
    if c.path:
        data["path"] = c.path
    return data


def _migrate(app_dir: Path) -> dict[str, Any]:
    """Convert CONFIG_JSON_DATA from downloader_config.json to consoles format."""
    cfg_path = app_dir / CONFIG_FILE
    if not cfg_path.exists():
        return {}
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg: dict[str, Any] = json.load(f)
        legacy: Any = cfg.get("CONFIG_JSON_DATA")
        if not isinstance(legacy, dict):
            return {}
        migrated: dict[str, Any] = {}
        for name, entry in legacy.items():
            if not isinstance(entry, dict) or not entry.get("url"):
                continue
            converted: dict[str, Any] = {"type": "direct_url", "url": entry["url"]}
            if entry.get("path"):
                converted["path"] = entry["path"]
            migrated[name] = converted
        if migrated:
            cfg.pop("CONFIG_JSON_DATA", None)
            try:
                with cfg_path.open("w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2)
            except OSError:
                log.warning("Could not remove legacy CONFIG_JSON_DATA from config file")
        return migrated
    except (json.JSONDecodeError, OSError):
        log.warning("Failed to migrate legacy console config")
        return {}


def _write(path: Path, data: dict[str, Any]) -> None:
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        raise OSError(f"Could not write {path.name}: {exc}") from exc
