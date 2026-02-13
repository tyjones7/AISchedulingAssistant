"""
Authentication store for BYU Learning Suite.

Manages browser-based authentication where users log in directly on BYU's site.
We store the authenticated session state, not passwords.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional
from enum import Enum

_SESSION_FILE = os.path.join(os.path.dirname(__file__), ".session_data.json")


class BrowserAuthStatus(str, Enum):
    """Status of browser-based authentication."""
    PENDING = "pending"
    OPENING = "opening"
    WAITING_FOR_LOGIN = "waiting_for_login"
    WAITING_FOR_MFA = "waiting_for_mfa"
    AUTHENTICATED = "authenticated"
    FAILED = "failed"


class BrowserAuthTask:
    """Represents a browser authentication task."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self.status = BrowserAuthStatus.PENDING
        self.error: Optional[str] = None
        self.started_at = datetime.now(timezone.utc)
        self.completed_at: Optional[datetime] = None
        self.scraper = None  # Will hold the authenticated scraper


# Store for browser auth tasks
_browser_auth_tasks: dict[str, BrowserAuthTask] = {}
_browser_auth_lock = threading.Lock()

# The currently authenticated scraper (if any)
_authenticated_scraper = None
_is_authenticated = False

# Session data for headless scraping (cookies + URL extracted from visible browser)
_session_cookies: list = []
_dynamic_base_url: str = ""

# Web storage data (localStorage/sessionStorage) for session persistence
_local_storage: dict = {}
_session_storage: dict = {}


def _save_session():
    """Persist session data (cookies, base_url, web storage) to disk."""
    data = {
        "cookies": _session_cookies,
        "dynamic_base_url": _dynamic_base_url,
        "local_storage": _local_storage,
        "session_storage": _session_storage,
    }
    try:
        with open(_SESSION_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def _load_session():
    """Load persisted session data from disk at module import time."""
    global _session_cookies, _dynamic_base_url, _is_authenticated
    global _local_storage, _session_storage
    if not os.path.exists(_SESSION_FILE):
        return
    try:
        with open(_SESSION_FILE, "r") as f:
            data = json.load(f)
        cookies = data.get("cookies", [])
        base_url = data.get("dynamic_base_url", "")
        if cookies and base_url:
            _session_cookies = cookies
            _dynamic_base_url = base_url
            _local_storage = data.get("local_storage", {})
            _session_storage = data.get("session_storage", {})
            _is_authenticated = True
    except Exception:
        pass


_load_session()


def create_browser_auth_task() -> str:
    """Create a new browser auth task.

    Returns:
        Task ID for polling status
    """
    task_id = str(uuid.uuid4())
    task = BrowserAuthTask(task_id)

    with _browser_auth_lock:
        _browser_auth_tasks[task_id] = task

    return task_id


def get_browser_auth_task(task_id: str) -> Optional[BrowserAuthTask]:
    """Get a browser auth task by ID."""
    return _browser_auth_tasks.get(task_id)


def update_browser_auth_status(task_id: str, status: BrowserAuthStatus, error: Optional[str] = None):
    """Update the status of a browser auth task."""
    with _browser_auth_lock:
        task = _browser_auth_tasks.get(task_id)
        if task:
            task.status = status
            if error:
                task.error = error
            if status in [BrowserAuthStatus.AUTHENTICATED, BrowserAuthStatus.FAILED]:
                task.completed_at = datetime.now(timezone.utc)


def set_authenticated(scraper=None):
    """Mark as authenticated with an optional scraper instance."""
    global _authenticated_scraper, _is_authenticated
    _authenticated_scraper = scraper
    _is_authenticated = True


def set_session_data(cookies: list, dynamic_base_url: str):
    """Store session cookies and URL for headless scraping.

    Called after visible browser login succeeds. The visible browser is then closed,
    and these cookies are injected into a headless browser when sync starts.
    """
    global _session_cookies, _dynamic_base_url, _is_authenticated, _authenticated_scraper
    _session_cookies = cookies
    _dynamic_base_url = dynamic_base_url
    _is_authenticated = True
    _authenticated_scraper = None  # No live scraper — we use cookies instead
    _save_session()


def set_web_storage(local_storage: dict, session_storage: dict):
    """Store localStorage and sessionStorage data from the visible browser.

    Some sites use web storage for session validation alongside cookies.
    This data is injected into the headless browser along with cookies.
    """
    global _local_storage, _session_storage
    _local_storage = local_storage or {}
    _session_storage = session_storage or {}
    _save_session()


def get_web_storage() -> tuple:
    """Get stored localStorage and sessionStorage data.

    Returns:
        Tuple of (local_storage dict, session_storage dict)
    """
    return _local_storage, _session_storage


def get_session_data() -> tuple:
    """Get stored session cookies and dynamic base URL.

    Returns:
        Tuple of (cookies list, dynamic_base_url string)
    """
    return _session_cookies, _dynamic_base_url


def get_authenticated_scraper():
    """Get the authenticated scraper if available."""
    return _authenticated_scraper


def is_authenticated() -> bool:
    """Check if user is authenticated."""
    return _is_authenticated


def clear_authentication():
    """Clear authentication state."""
    global _authenticated_scraper, _is_authenticated, _session_cookies, _dynamic_base_url
    global _local_storage, _session_storage
    if _authenticated_scraper:
        try:
            _authenticated_scraper.close()
        except:
            pass
    _authenticated_scraper = None
    _is_authenticated = False
    _session_cookies = []
    _dynamic_base_url = ""
    _local_storage = {}
    _session_storage = {}
    try:
        os.remove(_SESSION_FILE)
    except FileNotFoundError:
        pass
