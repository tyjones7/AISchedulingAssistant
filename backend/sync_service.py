"""
Canvas Sync Service

Orchestrates Canvas assignment sync with thread-safe status tracking for polling.
"""

import os
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import logging

from dotenv import load_dotenv
from supabase import create_client

import canvas_auth_store

load_dotenv()

logger = logging.getLogger(__name__)


class SyncStatus(str, Enum):
    """Status states for the sync process."""
    PENDING = "pending"
    CHECKING_SESSION = "checking_session"
    WAITING_FOR_MFA = "waiting_for_mfa"
    SCRAPING = "scraping"
    UPDATING_DB = "updating_db"
    COMPLETED = "completed"
    FAILED = "failed"


class SyncTask:
    """Represents a single sync task with its state."""

    def __init__(self, task_id: str, user_id: str):
        self.task_id = task_id
        self.user_id = user_id
        self.status = SyncStatus.PENDING
        self.message = "Initializing sync..."
        self.error: Optional[str] = None
        self.warnings: list[str] = []
        self.started_at = datetime.now(timezone.utc)
        self.completed_at: Optional[datetime] = None
        self.assignments_added = 0
        self.assignments_updated = 0
        self.courses_scraped = 0
        self.total_courses = 0
        self.current_course = 0
        self.current_course_name = ""


class SyncService:
    """Service for managing Learning Suite sync operations."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern to ensure only one sync service exists."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._tasks: dict[str, SyncTask] = {}
        self._current_task_id: Optional[str] = None
        self._task_lock = threading.Lock()
        self._setup_supabase()

    def _setup_supabase(self):
        """Set up Supabase client using service role key so RLS doesn't block writes."""
        url = os.getenv("SUPABASE_URL")
        # Prefer service key — bypasses RLS so sync can write for any user
        key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
        if url and key:
            self.supabase = create_client(url, key)
        else:
            self.supabase = None
            logger.warning("Supabase credentials not found")

    def start_sync(self, user_id: str) -> tuple[str, Optional[str]]:
        """Start a new sync task for a specific user.

        Returns:
            Tuple of (task_id, error_message). error_message is None if successful.
        """
        with self._task_lock:
            # Check if a sync is already in progress
            if self._current_task_id:
                current_task = self._tasks.get(self._current_task_id)
                if current_task and current_task.status not in [SyncStatus.COMPLETED, SyncStatus.FAILED]:
                    # Auto-expire syncs that have been running for more than 10 minutes —
                    # this handles crashes/hangs that leave _current_task_id set forever.
                    elapsed = (datetime.now(timezone.utc) - current_task.started_at).total_seconds()
                    if elapsed > 600:
                        logger.warning(f"Sync [{self._current_task_id[:8]}] appears stuck ({elapsed:.0f}s), force-expiring")
                        current_task.status = SyncStatus.FAILED
                        current_task.error = "Sync timed out after 10 minutes"
                        current_task.completed_at = datetime.now(timezone.utc)
                        self._current_task_id = None
                    else:
                        return "", "Sync already in progress"

            # Create new task
            task_id = str(uuid.uuid4())
            task = SyncTask(task_id, user_id)
            self._tasks[task_id] = task
            self._current_task_id = task_id

        # Start sync in background thread
        thread = threading.Thread(target=self._run_sync, args=(task_id, user_id), daemon=True)
        thread.start()

        return task_id, None

    def get_status(self, task_id: str) -> Optional[dict]:
        """Get the status of a sync task.

        Args:
            task_id: The task ID to check

        Returns:
            Dict with status info, or None if task not found
        """
        task = self._tasks.get(task_id)
        if not task:
            return None

        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "message": task.message,
            "error": task.error,
            "warnings": task.warnings,
            "started_at": task.started_at.isoformat(),
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "assignments_added": task.assignments_added,
            "assignments_updated": task.assignments_updated,
            "courses_scraped": task.courses_scraped,
            "total_courses": task.total_courses,
            "current_course": task.current_course,
            "current_course_name": task.current_course_name,
        }

    def get_last_sync(self, user_id: str) -> Optional[dict]:
        """Get the last sync metadata from the database for a specific user.

        Returns:
            Dict with last sync info, or None if no syncs recorded
        """
        if not self.supabase:
            return None

        try:
            response = self.supabase.table("sync_metadata").select("*").eq(
                "user_id", user_id
            ).order(
                "last_sync_at", desc=True
            ).limit(1).execute()

            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Error fetching last sync: {e}")
            return None

    def _update_task(self, task_id: str, status: SyncStatus, message: str):
        """Update task status thread-safely."""
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = status
                task.message = message
                logger.info(f"Sync [{task_id[:8]}]: {status.value} - {message}")

    def _run_sync(self, task_id: str, user_id: str):
        """Run Canvas sync in a background thread."""
        task = self._tasks.get(task_id)
        if not task:
            return

        canvas_token = canvas_auth_store.get_token(user_id)

        if not canvas_token:
            with self._task_lock:
                task.status = SyncStatus.FAILED
                task.error = "Canvas not connected. Please connect Canvas in Settings."
                task.message = f"Sync failed: {task.error}"
                task.completed_at = datetime.now(timezone.utc)
            self._save_sync_metadata(task_id, user_id, "failed", None, task.error)
            return

        try:
            # ---- Canvas sync ----
            if canvas_token:
                self._update_task(task_id, SyncStatus.SCRAPING, "Fetching Canvas assignments...")
                logger.info(f"Sync [{task_id[:8]}] - Starting Canvas sync...")

                from scraper.canvas_client import CanvasClient

                def canvas_progress(current, total, course_name):
                    with self._task_lock:
                        task.current_course = current
                        task.total_courses = total
                        task.current_course_name = course_name
                        task.message = f"Canvas: {course_name} ({current}/{total})" if current > 0 else f"Canvas: found {total} courses..."
                    logger.info(f"Sync [{task_id[:8]}] - Canvas {current}/{total}: {course_name}")

                try:
                    canvas = CanvasClient(canvas_token)
                    canvas_assignments = canvas.scrape_all_courses(progress_callback=canvas_progress)
                    # Pass the service-role supabase client and user_id so RLS is bypassed
                    canvas_result = canvas.update_database(
                        canvas_assignments,
                        supabase_client=self.supabase,
                        user_id=user_id,
                    )

                    with self._task_lock:
                        task.assignments_added += canvas_result.get("new", 0)
                        task.assignments_updated += canvas_result.get("modified", 0)
                        canvas_courses = set(a.get("course_name") for a in canvas_assignments if a.get("course_name"))
                        task.courses_scraped += len(canvas_courses)

                    logger.info(f"Sync [{task_id[:8]}] - Canvas: {canvas_result}")
                except Exception as e:
                    logger.error(f"Sync [{task_id[:8]}] - Canvas sync error: {e}")
                    raise

            # Build result summary for metadata
            result = {
                "courses_scraped": task.courses_scraped,
                "assignments_added": task.assignments_added,
                "assignments_updated": task.assignments_updated,
            }

            self._update_task(task_id, SyncStatus.UPDATING_DB, "Updating sync metadata...")
            self._save_sync_metadata(task_id, user_id, "success", result)

            with self._task_lock:
                task.status = SyncStatus.COMPLETED
                task.message = f"Sync complete! {task.assignments_added} new, {task.assignments_updated} updated from {task.courses_scraped} courses."
                task.completed_at = datetime.now(timezone.utc)

            logger.info(f"Sync [{task_id[:8]}] completed successfully")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Sync [{task_id[:8]}] failed: {error_msg}")

            with self._task_lock:
                task.status = SyncStatus.FAILED
                task.error = error_msg
                task.message = f"Sync failed: {error_msg}"
                task.completed_at = datetime.now(timezone.utc)

            # Save failed sync to metadata
            self._save_sync_metadata(task_id, user_id, "failed", None, error_msg)

        finally:
            with self._task_lock:
                if self._current_task_id == task_id:
                    self._current_task_id = None

    def _save_sync_metadata(self, task_id: str, user_id: str, status: str, result: Optional[dict], error: Optional[str] = None):
        """Save sync result to the sync_metadata table."""
        if not self.supabase:
            return

        try:
            summary = None
            if result:
                summary = {
                    "courses_scraped": result.get("courses_scraped", 0),
                    "assignments_added": result.get("assignments_added", 0),
                    "assignments_updated": result.get("assignments_updated", 0),
                }

            self.supabase.table("sync_metadata").insert({
                "user_id": user_id,
                "last_sync_at": datetime.now(timezone.utc).isoformat(),
                "last_sync_status": status,
                "last_sync_summary": summary,
                "last_sync_error": error,
            }).execute()

        except Exception as e:
            logger.error(f"Error saving sync metadata: {e}")


# Global sync service instance
sync_service = SyncService()
