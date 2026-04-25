"""SourceAdapter Protocol — the contract every adapter must satisfy."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import requests

from src.core.models import GameFile


@runtime_checkable
class SourceAdapter(Protocol):
    def fetch_gamelist(self) -> list[GameFile]:
        """Return the full list of available ROM files for this source."""
        ...

    def build_download_url(self, filename: str) -> str:
        """Return the absolute download URL for *filename*."""
        ...

    def get_session(self) -> requests.Session:
        """Return the HTTP session configured for this source."""
        ...
