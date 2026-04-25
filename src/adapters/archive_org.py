"""Adapter for Archive.org items (metadata API + direct download)."""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

import requests

from src.core.auth import get_authenticated_session
from src.core.constants import (
    ARCHIVE_ORG_DOWNLOAD_URL,
    ARCHIVE_ORG_METADATA_URL,
    ROM_EXTENSIONS,
)
from src.core.models import GameFile

log = logging.getLogger(__name__)
_USER_AGENT = "MyRD/1.7 (personal-rom-downloader)"


class ArchiveOrgAdapter:
    """Fetches file lists via the Archive.org metadata JSON API."""

    def __init__(
        self,
        identifier: str,
        extensions: list[str] | None = None,
        auth_email: str | None = None,
        auth_password: str | None = None,
    ) -> None:
        self._identifier = identifier
        self._extensions: frozenset[str] = (
            frozenset(ext.lower() for ext in extensions)
            if extensions
            else ROM_EXTENSIONS
        )
        self._session = get_authenticated_session(auth_email, auth_password)
        self._session.headers["User-Agent"] = _USER_AGENT

    # ------------------------------------------------------------------
    # SourceAdapter implementation
    # ------------------------------------------------------------------

    def fetch_gamelist(self) -> list[GameFile]:
        url = ARCHIVE_ORG_METADATA_URL.format(identifier=self._identifier)
        log.info("Fetching metadata from %s", url)
        response = self._session.get(url, timeout=30)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        files: list[dict[str, Any]] = data.get("files", [])
        log.debug("Archive.org returned %d total files for '%s'", len(files), self._identifier)

        result: list[GameFile] = []
        for entry in files:
            name: str = entry.get("name", "")
            if not name:
                continue
            ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
            if ext not in self._extensions:
                continue
            raw_size = entry.get("size", "0")
            size_bytes = int(raw_size) if str(raw_size).isdigit() else 0
            size_str = _format_bytes(size_bytes)
            result.append(GameFile(filename=name, size_str=size_str, size_bytes=size_bytes))

        log.info("Parsed %d matching games (from %d files) for '%s'", len(result), len(files), self._identifier)
        return sorted(result, key=lambda g: g.filename.lower())

    def build_download_url(self, filename: str) -> str:
        encoded = urllib.parse.quote(filename)
        return ARCHIVE_ORG_DOWNLOAD_URL.format(
            identifier=self._identifier,
            filename=encoded,
        )

    def get_session(self) -> requests.Session:
        return self._session


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _format_bytes(size: int) -> str:
    """Convert a byte count to a human-readable string (e.g. '1.2 GiB')."""
    if size <= 0:
        return "0 B"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    value = float(size)
    for unit in units[:-1]:
        if value < 1024.0:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} {units[-1]}"
