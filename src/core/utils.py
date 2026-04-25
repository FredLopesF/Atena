"""Shared utility functions used across multiple services."""

from __future__ import annotations


def sanitize_filename(name: str) -> str:
    """Remove unsafe characters from *name* for use as a file-system path component."""
    return "".join(
        c for c in name if c.isalnum() or c in " ._-()[]!"
    ).rstrip()
