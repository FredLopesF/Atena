"""Centralized logging configuration for Atena Emulation.

Call `setup()` once at startup (from main.py) to configure:
  - File handler: always active, writes to `logs/atena.log` with rotation.
  - Console handler: stderr output, level depends on --debug flag.

Usage in any module:
    import logging
    log = logging.getLogger(__name__)
    log.info("message")
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "atena.log"
MAX_BYTES = 2 * 1024 * 1024  # 2 MB per file
BACKUP_COUNT = 3  # keep 3 rotated copies

_FILE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_CONSOLE_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup(app_dir: Path, *, debug: bool = False) -> None:
    """Configure the root logger with file + console handlers.

    Parameters
    ----------
    app_dir:
        Application root directory.  A ``logs/`` subdirectory is created here.
    debug:
        If True, console output is set to DEBUG and the file handler also
        logs at DEBUG level.  Otherwise console is WARNING and file is INFO.
    """
    log_dir = app_dir / LOG_DIR_NAME
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / LOG_FILE_NAME

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # allow everything; handlers filter

    # Remove any pre-existing handlers (e.g. from basicConfig)
    root.handlers.clear()

    # --- File handler (always INFO+, or DEBUG in debug mode) ---
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(file_handler)

    # --- Console handler (stderr) ---
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.DEBUG if debug else logging.WARNING)
    console_handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(console_handler)

    # Startup banner
    mode = "DEBUG" if debug else "NORMAL"
    logging.info("=" * 60)
    logging.info("Atena Emulation — logging started (mode: %s)", mode)
    logging.info("Log file: %s", log_file)
    logging.info("=" * 60)
