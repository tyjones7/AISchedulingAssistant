"""
Canvas LMS authentication store.

Manages a personal access token for the Canvas API.
Follows the same pattern as auth_store.py (module-level state, disk persistence).
"""

import json
import os
import requests

_TOKEN_FILE = os.path.join(os.path.dirname(__file__), ".canvas_token.json")
CANVAS_BASE_URL = "https://byu.instructure.com"

_token: str | None = None
_user_name: str | None = None


def _save():
    """Persist token to disk."""
    try:
        with open(_TOKEN_FILE, "w") as f:
            json.dump({"token": _token, "user_name": _user_name}, f)
    except Exception:
        pass


def _load():
    """Load persisted token from disk at module import time."""
    global _token, _user_name
    if not os.path.exists(_TOKEN_FILE):
        return
    try:
        with open(_TOKEN_FILE, "r") as f:
            data = json.load(f)
        _token = data.get("token")
        _user_name = data.get("user_name")
    except Exception:
        pass


_load()


def validate_token(token: str) -> tuple[bool, str]:
    """Validate a Canvas API token by calling /api/v1/users/self.

    Returns:
        Tuple of (is_valid, user_name_or_error_message)
    """
    try:
        resp = requests.get(
            f"{CANVAS_BASE_URL}/api/v1/users/self",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            name = data.get("name") or data.get("short_name") or "Canvas User"
            return True, name
        elif resp.status_code == 401:
            return False, "Invalid token. Please check and try again."
        else:
            return False, f"Canvas API returned status {resp.status_code}"
    except requests.exceptions.ConnectionError:
        return False, "Could not connect to Canvas. Check your network."
    except requests.exceptions.Timeout:
        return False, "Connection to Canvas timed out."
    except Exception as e:
        return False, str(e)


def set_token(token: str, user_name: str = ""):
    """Store a validated Canvas token."""
    global _token, _user_name
    _token = token
    _user_name = user_name
    _save()


def get_token() -> str | None:
    """Get the stored Canvas token, or None."""
    return _token


def get_user_name() -> str | None:
    """Get the stored Canvas user name."""
    return _user_name


def clear_token():
    """Clear the stored token."""
    global _token, _user_name
    _token = None
    _user_name = None
    try:
        os.remove(_TOKEN_FILE)
    except FileNotFoundError:
        pass


def is_connected() -> bool:
    """Check if a Canvas token is stored."""
    return _token is not None
