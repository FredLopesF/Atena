"""Gamelist service — fetches a console's file list via adapter + cache."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from src.adapters import create_adapter
from src.core.models import Console, GameFile
from src.services import cache_service

log = logging.getLogger(__name__)


def fetch(
    console: Console,
    cache_dir: Path,
    on_status: Callable[[str, bool], None],
    force_refresh: bool = False,
) -> list[GameFile]:
    """Return the sorted list of GameFile for *console*.

    1. Checks the local cache (unless *force_refresh* is True).
    2. Falls back to the remote source via the appropriate adapter.
    3. Saves the result to cache before returning.

    *on_status(message, is_error)* is called for progress messages.
    Raises on network / parse errors — caller is responsible for handling.
    """
    if not force_refresh:
        cached = cache_service.get(cache_dir, console.name)
        if cached is not None:
            on_status(f"Loading {console.name} games from cache.", False)
            return cached

    label = "Force refreshing" if force_refresh else "Fetching"
    on_status(f"{label} game list for {console.name}...", False)

    adapter = create_adapter(console)
    games = adapter.fetch_gamelist()

    cache_service.put(cache_dir, console.name, games)
    on_status(f"Saved {console.name} list to cache.", False)

    return games
