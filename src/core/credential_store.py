"""Secure credential storage using the OS keyring (Windows Credential Manager)."""

from __future__ import annotations

import logging

import keyring

_SERVICE = "MyRD"


def save(console_name: str, email: str, password: str) -> None:
    """Store credentials for *console_name* in the OS keyring."""
    keyring.set_password(_SERVICE, f"{console_name}:email", email)
    keyring.set_password(_SERVICE, f"{console_name}:password", password)
    logging.info("Credentials saved for '%s'.", console_name)


def load(console_name: str) -> tuple[str | None, str | None]:
    """Return (email, password) from the OS keyring, or (None, None)."""
    email = keyring.get_password(_SERVICE, f"{console_name}:email")
    password = keyring.get_password(_SERVICE, f"{console_name}:password")
    return email, password


def delete(console_name: str) -> None:
    """Remove credentials for *console_name* from the OS keyring."""
    for key in (f"{console_name}:email", f"{console_name}:password"):
        try:
            keyring.delete_password(_SERVICE, key)
        except keyring.errors.PasswordDeleteError:
            pass
