"""Atena Emulation — entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.core.logging_config import setup as setup_logging


def _get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Atena Emulation — ROM downloader and manager.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode (verbose logging to console and log file).",
    )
    args = parser.parse_args()

    app_dir = _get_app_dir()
    setup_logging(app_dir, debug=args.debug)

    from src.ui.app import GameDownloaderApp

    app = GameDownloaderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
