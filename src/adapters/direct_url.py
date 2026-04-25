"""Adapter for directory-listing HTTP sources (Apache/nginx).

Uses CloudScraper so Cloudflare-protected servers are handled transparently.
"""

from __future__ import annotations

import urllib.parse

import cloudscraper
import requests
from bs4 import BeautifulSoup

from src.core.constants import ROM_EXTENSIONS
from src.core.models import GameFile


class DirectUrlAdapter:
    """Scrapes an HTML directory listing and builds download URLs."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._session: requests.Session = cloudscraper.create_scraper()

    # ------------------------------------------------------------------
    # SourceAdapter implementation
    # ------------------------------------------------------------------

    def fetch_gamelist(self) -> list[GameFile]:
        response = self._session.get(self._base_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        result: list[GameFile] = []
        for row in soup.find_all("tr"):
            link_tag = row.find("a")
            if not link_tag:
                continue
            href: str = link_tag.get("href", "")
            if (
                not href
                or href.startswith(("?", "#", "/"))
                or href == "../"
                or "://" in href
            ):
                continue
            decoded = urllib.parse.unquote_plus(href)
            filename = decoded.split("/")[-1]
            ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
            if ext not in ROM_EXTENSIONS:
                continue
            tds = row.find_all("td")
            size_str = tds[1].text.strip() if len(tds) > 1 else "-"
            if size_str and size_str != "-":
                result.append(GameFile(filename=filename, size_str=size_str, size_bytes=0))

        return result

    def build_download_url(self, filename: str) -> str:
        return urllib.parse.urljoin(self._base_url, urllib.parse.quote(filename))

    def get_session(self) -> requests.Session:
        return self._session
