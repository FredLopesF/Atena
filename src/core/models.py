from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class Console:
    name: str
    type: Literal["archive_org", "direct_url"]
    identifier: str | None = None
    url: str | None = None
    extensions: list[str] = field(default_factory=list)
    path: str | None = None
    auth_email: str | None = None
    auth_password: str | None = None


@dataclass
class GameFile:
    filename: str
    size_str: str
    size_bytes: int = 0


@dataclass
class DownloadItem:
    game: GameFile
    url: str
    local_path: Path
    status: Literal["pending", "downloading", "done", "failed", "skipped"] = "pending"


@dataclass
class DownloadStats:
    downloaded: int = 0
    failed: int = 0
    skipped: int = 0
    total_bytes: int = 0
