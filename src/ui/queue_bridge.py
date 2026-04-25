"""QueueBridge — converts service callbacks into queue messages.

Services receive plain Callable arguments and never touch a queue.
QueueBridge wraps queue.Queue and returns factory callables that enqueue
typed messages.  The UI polls queue.Queue via self.after(100, _poll).
"""

from __future__ import annotations

import queue
from typing import Any, Callable

from src.core.models import DownloadItem, DownloadStats


# Message type aliases for readability
_Msg = tuple[str, Any]


class QueueBridge:
    def __init__(self) -> None:
        self._q: queue.Queue[_Msg] = queue.Queue()

    # ------------------------------------------------------------------
    # Queue access
    # ------------------------------------------------------------------

    @property
    def q(self) -> queue.Queue[_Msg]:
        return self._q

    # ------------------------------------------------------------------
    # Direct put helpers (used by thread wrappers in app.py)
    # ------------------------------------------------------------------

    def put_status(self, message: str, error: bool = False) -> None:
        self._q.put(("status", {"message": message, "error": error}))

    def put_gamelist_ok(self, console_name: str, games: list[Any]) -> None:
        self._q.put(
            ("gamelist_load_complete", {"success": True, "console": console_name, "games": games})
        )

    def put_gamelist_err(self, error: str) -> None:
        self._q.put(("gamelist_load_complete", {"success": False, "error": error}))

    def put_prepare_complete(self, items: list[DownloadItem]) -> None:
        self._q.put(("prepare_complete", {"items": items}))

    def put_download_cancelled(self) -> None:
        self._q.put(("download_cancelled", {}))

    def put_fake_complete(self, created: int, skipped: int, errors: int) -> None:
        self._q.put(
            ("fake_creation_complete", {"created_count": created, "skipped_count": skipped, "error_count": errors})
        )

    # ------------------------------------------------------------------
    # Callback factories (passed to services)
    # ------------------------------------------------------------------

    def make_status_cb(self) -> Callable[[str, bool], None]:
        return self.put_status

    @staticmethod
    def _pct(done: int, total: int) -> int:
        return int(done / total * 100) if total > 0 else 0

    def make_prep_progress_cb(self) -> Callable[[int, int], None]:
        def cb(done: int, total: int) -> None:
            self._q.put(("prep_progress", {"percent": self._pct(done, total)}))
        return cb

    def make_bytes_cb(self) -> Callable[[int, int], None]:
        def cb(chunk_bytes: int, total_size: int) -> None:
            self._q.put(
                ("progress_update", {"add_bytes": chunk_bytes, "add_total_size": total_size})
            )
        return cb

    def make_file_done_cb(self) -> Callable[[DownloadItem, bool, str], None]:
        def cb(item: DownloadItem, success: bool, error: str) -> None:
            self._q.put(("file_complete", {"item": item, "success": success, "error": error}))
        return cb

    def make_complete_cb(self) -> Callable[[DownloadStats], None]:
        def cb(stats: DownloadStats) -> None:
            self._q.put(("download_complete", stats))
        return cb

    def make_fake_progress_cb(self) -> Callable[[int, int], None]:
        def cb(done: int, total: int) -> None:
            self._q.put(("fake_progress", {"percent": self._pct(done, total)}))
        return cb
