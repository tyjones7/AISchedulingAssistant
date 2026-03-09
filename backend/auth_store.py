"""
Authentication store for BYU Learning Suite.

Manages browser-based authentication where users log in directly on BYU's site.
We store the authenticated session state, not passwords.

Per-user sessions are stored in memory and persisted to Supabase (user_sessions table).
"""

import logging
import os
import threading
import uuid

logger = logging.getLogger(__name__)
from datetime import datetime, timezone
from typing import Optional
from enum import Enum


class BrowserAuthStatus(str, Enum):
    """Status of browser-based authentication."""
    PENDING = "pending"
    OPENING = "opening"
    WAITING_FOR_LOGIN = "waiting_for_login"
    WAITING_FOR_MFA = "waiting_for_mfa"
    WAITING_FOR_DUO_PASSCODE = "waiting_for_duo_passcode"
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


# Browser auth tasks are short-lived (one per login attempt) — no user_id needed
_browser_auth_tasks: dict[str, BrowserAuthTask] = {}
_browser_auth_lock = threading.Lock()

# Duo passcode coordination: task_id → (Event, passcode)
_duo_events: dict[str, threading.Event] = {}
_duo_passcodes: dict[str, str] = {}


def wait_for_duo_passcode(task_id: str, timeout: float = 300.0) -> Optional[str]:
    """Block until the user submits a Duo passcode via the API, or timeout."""
    event = threading.Event()
    _duo_events[task_id] = event
    # Already submitted before we started waiting?
    if task_id in _duo_passcodes:
        _duo_events.pop(task_id, None)
        return _duo_passcodes.pop(task_id)
    event.wait(timeout=timeout)
    _duo_events.pop(task_id, None)
    return _duo_passcodes.pop(task_id, None)


def set_duo_passcode(task_id: str, code: str):
    """Called when the user submits their Duo passcode from the frontend."""
    _duo_passcodes[task_id] = code
    event = _duo_events.get(task_id)
    if event:
        event.set()

# Per-user session data: user_id -> {cookies, base_url, local_storage, session_storage}
_sessions: dict[str, dict] = {}


def _get_supabase():
    """Create a Supabase client using the service key (bypasses RLS)."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    if url and key:
        try:
            from supabase import create_client
            return create_client(url, key)
        except Exception as e:
            logger.warning(f"auth_store: could not create Supabase client: {e}")
    return None


# ============================================================
# Browser Auth Task API (unchanged — no user_id needed)
# ============================================================

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


# ============================================================
# Per-User Session API
# ============================================================

def set_session_data(user_id: str, cookies: list, dynamic_base_url: str):
    """Store session cookies and URL for headless scraping.

    Called after visible browser login succeeds. Persists to Supabase so the
    session survives server restarts.
    """
    _sessions[user_id] = {
        "cookies": cookies,
        "base_url": dynamic_base_url,
        "local_storage": _sessions.get(user_id, {}).get("local_storage", {}),
        "session_storage": _sessions.get(user_id, {}).get("session_storage", {}),
    }

    sb = _get_supabase()
    if sb:
        try:
            sb.table("user_sessions").upsert({
                "user_id": user_id,
                "cookies": cookies,
                "base_url": dynamic_base_url,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="user_id").execute()
        except Exception as e:
            logger.warning(f"auth_store: failed to persist session for {user_id}: {e}")


def set_web_storage(user_id: str, local_storage: dict, session_storage: dict):
    """Store localStorage and sessionStorage data from the visible browser.

    Some sites use web storage for session validation alongside cookies.
    This data is injected into the headless browser along with cookies.
    """
    if user_id not in _sessions:
        _sessions[user_id] = {"cookies": [], "base_url": "", "local_storage": {}, "session_storage": {}}
    _sessions[user_id]["local_storage"] = local_storage or {}
    _sessions[user_id]["session_storage"] = session_storage or {}

    sb = _get_supabase()
    if sb:
        try:
            sb.table("user_sessions").upsert({
                "user_id": user_id,
                "local_storage": local_storage or {},
                "session_storage": session_storage or {},
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="user_id").execute()
        except Exception as e:
            logger.warning(f"auth_store: failed to persist web storage for {user_id}: {e}")


def get_session_data(user_id: str) -> tuple:
    """Get stored session cookies and dynamic base URL.

    Checks in-memory dict first, then loads from Supabase if not found.

    Returns:
        Tuple of (cookies list, dynamic_base_url string)
    """
    if user_id in _sessions:
        s = _sessions[user_id]
        return s.get("cookies", []), s.get("base_url", "")

    # Try loading from Supabase
    sb = _get_supabase()
    if sb:
        try:
            r = sb.table("user_sessions").select("*").eq("user_id", user_id).execute()
            if r.data:
                row = r.data[0]
                _sessions[user_id] = {
                    "cookies": row.get("cookies") or [],
                    "base_url": row.get("base_url") or "",
                    "local_storage": row.get("local_storage") or {},
                    "session_storage": row.get("session_storage") or {},
                }
                return _sessions[user_id]["cookies"], _sessions[user_id]["base_url"]
        except Exception as e:
            logger.warning(f"auth_store: failed to load session for {user_id}: {e}")

    return [], ""


def get_web_storage(user_id: str) -> tuple:
    """Get stored localStorage and sessionStorage data.

    Returns:
        Tuple of (local_storage dict, session_storage dict)
    """
    if user_id not in _sessions:
        # Trigger a load from Supabase (get_session_data populates the full record)
        get_session_data(user_id)

    s = _sessions.get(user_id, {})
    return s.get("local_storage", {}), s.get("session_storage", {})


def get_authenticated_scraper(user_id: str = None):
    """Get the authenticated scraper if available.

    Scrapers are not stored per-user (they are ephemeral during sync).
    Returns None always — the HTTP-only session path is used for syncs.
    """
    return None


def is_authenticated(user_id: str) -> bool:
    """Check if a user has a stored session (cookies + base_url)."""
    cookies, base_url = get_session_data(user_id)
    return bool(cookies and base_url)


def clear_authentication(user_id: str):
    """Clear authentication state for a user (memory + Supabase)."""
    _sessions.pop(user_id, None)

    sb = _get_supabase()
    if sb:
        try:
            sb.table("user_sessions").delete().eq("user_id", user_id).execute()
        except Exception as e:
            logger.warning(f"auth_store: failed to delete session for {user_id}: {e}")


# ──────────────────────────────────────────────────────────────
# Legacy no-op: set_authenticated is called from browser auth
# thread after a successful login (before set_session_data).
# Kept so existing call sites don't break.
# ──────────────────────────────────────────────────────────────
def set_authenticated(scraper=None):
    """No-op — superseded by set_session_data(user_id, ...)."""
    pass
