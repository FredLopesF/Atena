"""Archive.org authentication — creates an authenticated requests.Session.

Sessions are cached by (email, password) for the lifetime of the process,
so repeated calls with the same credentials reuse the existing session
instead of logging in again.
"""

from __future__ import annotations

import logging

import requests

# Module-level session cache: (email, password) → Session
_cache: dict[tuple[str, str], requests.Session] = {}


def get_authenticated_session(email: str | None, password: str | None) -> requests.Session:
    """Return a requests.Session, logging into Archive.org if credentials are provided.

    Returns an unauthenticated session when either credential is absent.
    Cached per (email, password) — subsequent calls with the same credentials
    return the same session without re-authenticating.
    """
    if not email or not password:
        return requests.Session()

    key = (email, password)
    if key in _cache:
        return _cache[key]

    session = requests.Session()
    try:
        response = session.get("https://archive.org/services/account/login/", timeout=15)
        response.raise_for_status()
        login_data = response.json()

        if not login_data.get("success"):
            logging.warning("Failed to get Archive.org login token.")
            return session

        login_token = login_data["value"]["token"]
        payload = {"username": email, "password": password, "t": login_token}

        response = session.post(
            "https://archive.org/services/account/login/",
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        res_json = response.json()

        if res_json.get("success"):
            logging.info("Archive.org authentication successful.")
            _cache[key] = session
        else:
            logging.warning("Archive.org authentication failed: %s", res_json)

    except Exception as exc:
        logging.error("Archive.org authentication error: %s", exc)

    return session
