"""
Authentication store for BYU Learning Suite.

Manages browser-based authentication where users log in directly on BYU's site.
We store the authenticated session state, not passwords.
"""

import threading
import uuid
from datetime import datetime
from typing import Optional
from enum import Enum


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
        self.started_at = datetime.now()
        self.completed_at: Optional[datetime] = None
        self.scraper = None  # Will hold the authenticated scraper


# Store for browser auth tasks
_browser_auth_tasks: dict[str, BrowserAuthTask] = {}
_browser_auth_lock = threading.Lock()

# The currently authenticated scraper (if any)
_authenticated_scraper = None
_is_authenticated = False


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
                task.completed_at = datetime.now()


def set_authenticated(scraper=None):
    """Mark as authenticated with an optional scraper instance."""
    global _authenticated_scraper, _is_authenticated
    _authenticated_scraper = scraper
    _is_authenticated = True


def get_authenticated_scraper():
    """Get the authenticated scraper if available."""
    return _authenticated_scraper


def is_authenticated() -> bool:
    """Check if user is authenticated."""
    return _is_authenticated


def clear_authentication():
    """Clear authentication state."""
    global _authenticated_scraper, _is_authenticated
    if _authenticated_scraper:
        try:
            _authenticated_scraper.close()
        except:
            pass
    _authenticated_scraper = None
    _is_authenticated = False
