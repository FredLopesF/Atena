"""Adapter for Archive.org ZIP files using HTTP Range requests.

This parses the central directory of a massive remote .zip file
without downloading it, allowing us to list the ROMs inside it.
"""

from __future__ import annotations

import urllib.parse
import zipfile

import requests

from src.adapters.archive_org import _format_bytes
from src.core.auth import get_authenticated_session
from src.core.constants import ROM_EXTENSIONS
from src.core.models import GameFile


class HttpRangeFile:
    """A file-like object that reads arbitrary ranges of a remote file via HTTP."""

    def __init__(self, url: str, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        res = self._session.head(url, allow_redirects=True, timeout=10)
        res.raise_for_status()
        self.url = res.url  # Use final URL after redirects
        self.size = int(res.headers.get("Content-Length", 0))
        if self.size == 0:
            raise ValueError("URL does not support Content-Length or is empty.")
        self.pos = 0

    def read(self, size: int = -1) -> bytes:
        """Read `size` bytes from the current position using HTTP Range."""
        if size == -1:
            size = self.size - self.pos
        if size <= 0:
            return b""
        end = self.pos + size - 1
        if end >= self.size:
            end = self.size - 1
            
        headers = {"Range": f"bytes={self.pos}-{end}"}
        res = self._session.get(self.url, headers=headers, timeout=10)
        res.raise_for_status()
        
        chunk = res.content
        self.pos += len(chunk)
        return chunk

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            self.pos = offset
        elif whence == 1:
            self.pos += offset
        elif whence == 2:
            self.pos = self.size + offset
        
        self.pos = max(0, min(self.pos, self.size))
        return self.pos

    def tell(self) -> int:
        return self.pos

    def seekable(self) -> bool:
        return True

    def close(self) -> None:
        pass  # Session lifecycle is managed by the adapter, not the range file.


class ArchiveOrgZipAdapter:
    """Adapter for a single large .zip file on Archive.org containing ROMs."""

    def __init__(self, base_url: str, auth_email: str | None = None, auth_password: str | None = None) -> None:
        # Remove trailing slash if present (e.g. "...zip/")
        self._base_url = base_url.rstrip("/")
        self._session = get_authenticated_session(auth_email, auth_password)

    def fetch_gamelist(self) -> list[GameFile]:
        """Fetch ZIP central directory and return its internal files."""
        result: list[GameFile] = []
        
        # We use a context manager to ensure the Range file is cleaned up
        range_file = HttpRangeFile(self._base_url, session=self._session)
        try:
            with zipfile.ZipFile(range_file) as z:
                for info in z.infolist():
                    # Ignore directories
                    if info.is_dir():
                        continue
                        
                    filename = info.filename
                    # Strip directories inside the zip if they exist (basename)
                    basename = filename.split("/")[-1]
                    
                    ext = ("." + basename.rsplit(".", 1)[-1].lower()) if "." in basename else ""
                    if ext not in ROM_EXTENSIONS:
                        continue
                        
                    size_bytes = info.file_size
                    size_str = _format_bytes(size_bytes)
                    result.append(GameFile(filename=filename, size_str=size_str, size_bytes=size_bytes))
        finally:
            range_file.close()

        # Archive.org ZIP listings should already be somewhat sorted, but let's enforce
        result.sort(key=lambda g: g.filename.lower())
        return result

    def build_download_url(self, filename: str) -> str:
        """Archive.org allows downloading a file inside a zip by appending /filename."""
        # Archive.org expects the exact path inside the zip, url-encoded
        encoded = urllib.parse.quote(filename)
        return f"{self._base_url}/{encoded}"

    def get_session(self) -> requests.Session:
        return self._session
