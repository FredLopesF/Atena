"""Download service — two-phase prepare + download with callbacks.

Phase 1 (prepare): checks local disk and resolves download URLs.
Phase 2 (download): streams files with pause/cancel/retry support.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import requests

from src.adapters import SourceAdapter, create_adapter
from src.core.constants import DOWNLOAD_RETRIES, MAX_URL_WORKERS, RETRY_DELAY_S
from src.core.models import Console, DownloadItem, DownloadStats, GameFile
from src.services import history_service

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase 1 — Prepare
# ---------------------------------------------------------------------------


def prepare(
    console: Console,
    games: list[GameFile],
    download_path: Path,
    on_progress: Callable[[int, int], None],
    on_status: Callable[[str, bool], None],
    cancel_event: threading.Event,
    pause_event: threading.Event,
) -> list[DownloadItem]:
    """Check local existence and resolve download URLs for *games*.

    Returns a list of DownloadItem with status 'pending' or 'skipped'.
    Returns [] if cancelled.
    """
    adapter = create_adapter(console)
    total = len(games)
    done = 0
    items: list[DownloadItem] = []

    on_progress(0, total)

    with ThreadPoolExecutor(max_workers=MAX_URL_WORKERS) as pool:
        futures = {
            pool.submit(
                _check_one,
                game,
                download_path,
                adapter,
                on_status,
                cancel_event,
                pause_event,
            ): game
            for game in games
            if not cancel_event.is_set()
        }

        if cancel_event.is_set():
            for f in futures:
                f.cancel()
            return []

        for future in as_completed(futures):
            if cancel_event.is_set():
                break
            try:
                items.append(future.result())
            except CancelledError:
                pass
            except Exception:
                log.exception("Error preparing game '%s'", futures[future].filename)
            done += 1
            on_progress(done, total)

    return [] if cancel_event.is_set() else items


def _check_one(
    game: GameFile,
    download_path: Path,
    adapter: SourceAdapter,
    on_status: Callable[[str, bool], None],
    cancel_event: threading.Event,
    pause_event: threading.Event,
) -> DownloadItem:
    if cancel_event.is_set():
        raise CancelledError()
    while pause_event.is_set():
        time.sleep(0.2)
        if cancel_event.is_set():
            raise CancelledError()

    local_path = download_path / game.filename

    if local_path.exists():
        on_status(f"Skipping '{game.filename}' (already exists).", False)
        return DownloadItem(game=game, url="", local_path=local_path, status="skipped")

    url = adapter.build_download_url(game.filename)
    on_status(f"Preparing '{game.filename}' for download.", False)
    return DownloadItem(game=game, url=url, local_path=local_path, status="pending")


# ---------------------------------------------------------------------------
# Phase 2 — Download
# ---------------------------------------------------------------------------


def download(
    items: list[DownloadItem],
    console: Console,
    db_dir: Path,
    on_bytes: Callable[[int, int], None],
    on_file_done: Callable[[DownloadItem, bool, str], None],
    on_complete: Callable[[DownloadStats], None],
    on_status: Callable[[str, bool], None],
    cancel_event: threading.Event,
    pause_event: threading.Event,
    workers: int = 4,
) -> None:
    """Download all pending items.  Calls *on_complete* when finished.

    on_bytes(chunk_bytes, total_size): progress per chunk.
    on_file_done(item, success, error): called once per file.
    on_complete(stats): called after all files (not called on cancel).
    """
    adapter = create_adapter(console)
    session = adapter.get_session()
    pending = [i for i in items if i.status == "pending"]
    stats = DownloadStats(skipped=sum(1 for i in items if i.status == "skipped"))

    pending[0].local_path.parent.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _download_one,
                item,
                session,
                on_bytes,
                on_status,
                cancel_event,
                pause_event,
            ): item
            for item in pending
            if not cancel_event.is_set()
        }

        if cancel_event.is_set():
            for f in futures:
                f.cancel()

        for future in as_completed(futures):
            item = futures[future]
            if cancel_event.is_set() and not future.done():
                future.cancel()
                continue
            try:
                success, error = future.result()
            except CancelledError:
                success, error = False, "Cancelled"
            except Exception as exc:
                success, error = False, str(exc)

            if success:
                item.status = "done"
                stats.downloaded += 1
                history_service.record(db_dir, console.name, item.game.filename)
                if item.local_path.exists():
                    stats.total_bytes += item.local_path.stat().st_size
            else:
                item.status = "failed"
                stats.failed += 1

            on_file_done(item, success, error)

    if cancel_event.is_set():
        _cleanup_partial(pending)
    else:
        on_complete(stats)


def _download_one(
    item: DownloadItem,
    session: requests.Session,
    on_bytes: Callable[[int, int], None],
    on_status: Callable[[str, bool], None],
    cancel_event: threading.Event,
    pause_event: threading.Event,
) -> tuple[bool, str]:
    error = "Download failed"
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        if cancel_event.is_set():
            raise CancelledError()
        while pause_event.is_set():
            time.sleep(0.2)
            if cancel_event.is_set():
                raise CancelledError()

        success, error = _stream(
            item, session, on_bytes, on_status, cancel_event, pause_event, attempt
        )
        if success:
            return True, ""

        if attempt < DOWNLOAD_RETRIES:
            on_status(f"'{item.game.filename}' failed ({error}). Retrying...", True)
            for _ in range(RETRY_DELAY_S):
                time.sleep(1)
                if cancel_event.is_set():
                    raise CancelledError()
        else:
            on_status(
                f"Download failed for '{item.game.filename}' after {DOWNLOAD_RETRIES} attempts.",
                True,
            )
            item.local_path.unlink(missing_ok=True)

    return False, error


def _stream(
    item: DownloadItem,
    session: requests.Session,
    on_bytes: Callable[[int, int], None],
    on_status: Callable[[str, bool], None],
    cancel_event: threading.Event,
    pause_event: threading.Event,
    attempt: int,
) -> tuple[bool, str]:
    error = "Download failed"
    response: requests.Response | None = None
    succeeded = False
    paused_msg_sent = False

    try:
        if cancel_event.is_set():
            raise CancelledError()

        response = session.get(
            item.url, stream=True, timeout=(15, 600), allow_redirects=True
        )
        response.raise_for_status()

        has_exact_size = "content-length" in response.headers
        total_size = int(response.headers.get("content-length", 0))

        if total_size == 0 and item.game.size_str:
            size_str = item.game.size_str.lower()
            val = float(size_str.split()[0]) if size_str.split() else 0.0
            if "gib" in size_str:
                total_size = int(val * 1024**3)
            elif "mib" in size_str:
                total_size = int(val * 1024**2)
            elif "kib" in size_str:
                total_size = int(val * 1024)
            else:
                total_size = int(val)

        if attempt == 1:
            mb = total_size / 1_048_576 if total_size else 0
            on_status(f"Starting '{item.game.filename}' ({mb:.2f} MB).", False)
            on_bytes(0, total_size)

        bytes_done = 0
        item.local_path.parent.mkdir(parents=True, exist_ok=True)

        with item.local_path.open("wb") as fp:
            for chunk in response.iter_content(chunk_size=1_048_576):
                while pause_event.is_set():
                    if cancel_event.is_set():
                        raise CancelledError()
                    if not paused_msg_sent:
                        on_status(f"Paused: {item.game.filename}", False)
                        paused_msg_sent = True
                    time.sleep(0.5)

                if cancel_event.is_set():
                    raise CancelledError()

                if paused_msg_sent:
                    on_status(f"Resuming: {item.game.filename}", False)
                    paused_msg_sent = False

                if chunk:
                    fp.write(chunk)
                    bytes_done += len(chunk)
                    on_bytes(len(chunk), total_size)

        if has_exact_size and total_size > 0 and bytes_done < total_size:
            raise requests.exceptions.RequestException("Incomplete download")

        succeeded = True
        return True, ""

    except CancelledError:
        raise
    except requests.exceptions.HTTPError as exc:
        error = f"HTTP {exc.response.status_code}"
    except requests.exceptions.RequestException as exc:
        error = f"Connection error: {exc.__class__.__name__}"
    except OSError as exc:
        error = f"File system error: {exc.strerror}"
    except Exception:
        log.exception("Unexpected error downloading '%s'", item.game.filename)
        error = "Unexpected error"
    finally:
        if response:
            response.close()
        if not succeeded and item.local_path.exists():
            item.local_path.unlink(missing_ok=True)

    return False, error


def _cleanup_partial(items: list[DownloadItem]) -> None:
    for item in items:
        if item.status in ("pending", "downloading"):
            item.local_path.unlink(missing_ok=True)
