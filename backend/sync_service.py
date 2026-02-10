"""
Sync Service for Learning Suite

Orchestrates the sync process with thread-safe status tracking for polling.
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

from scraper.learning_suite_scraper import LearningSuiteScraper
import auth_store

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

    def __init__(self, task_id: str):
        self.task_id = task_id
        self.status = SyncStatus.PENDING
        self.message = "Initializing sync..."
        self.error: Optional[str] = None
        self.started_at = datetime.now(timezone.utc)
        self.completed_at: Optional[datetime] = None
        self.assignments_added = 0
        self.assignments_updated = 0
        self.courses_scraped = 0


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
        """Set up Supabase client."""
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if url and key:
            self.supabase = create_client(url, key)
        else:
            self.supabase = None
            logger.warning("Supabase credentials not found")

    def start_sync(self) -> tuple[str, Optional[str]]:
        """Start a new sync task.

        Returns:
            Tuple of (task_id, error_message). error_message is None if successful.
        """
        with self._task_lock:
            # Check if a sync is already in progress
            if self._current_task_id:
                current_task = self._tasks.get(self._current_task_id)
                if current_task and current_task.status not in [SyncStatus.COMPLETED, SyncStatus.FAILED]:
                    return "", "Sync already in progress"

            # Create new task
            task_id = str(uuid.uuid4())
            task = SyncTask(task_id)
            self._tasks[task_id] = task
            self._current_task_id = task_id

        # Start sync in background thread
        thread = threading.Thread(target=self._run_sync, args=(task_id,), daemon=True)
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
            "started_at": task.started_at.isoformat(),
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "assignments_added": task.assignments_added,
            "assignments_updated": task.assignments_updated,
            "courses_scraped": task.courses_scraped,
        }

    def get_last_sync(self) -> Optional[dict]:
        """Get the last sync metadata from the database.

        Returns:
            Dict with last sync info, or None if no syncs recorded
        """
        if not self.supabase:
            return None

        try:
            response = self.supabase.table("sync_metadata").select("*").order(
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

    def _run_sync(self, task_id: str):
        """Run the sync process in a background thread."""
        task = self._tasks.get(task_id)
        if not task:
            return

        scraper = None
        should_close_scraper = False  # Track if we created the scraper or got it from auth_store

        try:
            self._update_task(task_id, SyncStatus.CHECKING_SESSION, "Checking authentication...")
            logger.info(f"Sync [{task_id[:8]}] - Checking for authenticated session...")

            # First, check if we have an authenticated scraper from browser login
            scraper = auth_store.get_authenticated_scraper()

            if scraper and scraper.driver:
                logger.info(f"Sync [{task_id[:8]}] - Using existing authenticated session")
                self._update_task(task_id, SyncStatus.SCRAPING, "Using authenticated session...")
                should_close_scraper = False  # Don't close the shared scraper
            else:
                # No authenticated session - try headless check
                logger.info(f"Sync [{task_id[:8]}] - No authenticated session, trying headless...")
                self._update_task(task_id, SyncStatus.CHECKING_SESSION, "Starting browser...")

                scraper = LearningSuiteScraper(headless=True)
                should_close_scraper = True
                scraper._setup_driver()

                self._update_task(task_id, SyncStatus.CHECKING_SESSION, "Checking login status...")
                already_logged_in = scraper.check_already_logged_in()

                if already_logged_in:
                    self._update_task(task_id, SyncStatus.SCRAPING, "Session found, scraping...")
                else:
                    scraper.close()
                    raise ValueError("Not authenticated. Please sign in with BYU first.")

            # Scrape all courses - returns list of assignments
            self._update_task(task_id, SyncStatus.SCRAPING, "Scraping assignments from courses...")
            assignments = scraper.scrape_all_courses()
            logger.info(f"Sync [{task_id[:8]}] - Scraped {len(assignments)} assignments")

            # Update database with scraped assignments
            self._update_task(task_id, SyncStatus.UPDATING_DB, "Saving to database...")
            db_result = scraper.update_database(assignments)
            logger.info(f"Sync [{task_id[:8]}] - Database update: {db_result}")

            # Extract stats from the database update result
            with self._task_lock:
                # Count unique courses from assignments
                courses = set(a.get("course_name") for a in assignments if a.get("course_name"))
                task.courses_scraped = len(courses)
                task.assignments_added = db_result.get("new", 0)
                task.assignments_updated = db_result.get("modified", 0)

            # Build result summary for metadata
            result = {
                "courses_scraped": task.courses_scraped,
                "assignments_added": task.assignments_added,
                "assignments_updated": task.assignments_updated,
                "total_scraped": len(assignments),
            }

            self._update_task(task_id, SyncStatus.UPDATING_DB, "Updating sync metadata...")

            # Update sync_metadata table
            self._save_sync_metadata(task_id, "success", result)

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
            self._save_sync_metadata(task_id, "failed", None, error_msg)

        finally:
            # Only close scraper if we created it (not the shared authenticated one)
            if scraper and should_close_scraper:
                try:
                    scraper.close()
                except:
                    pass

            with self._task_lock:
                if self._current_task_id == task_id:
                    self._current_task_id = None

    def _save_sync_metadata(self, task_id: str, status: str, result: Optional[dict], error: Optional[str] = None):
        """Save sync result to the sync_metadata table."""
        if not self.supabase:
            return

        try:
            task = self._tasks.get(task_id)
            summary = None
            if result:
                summary = {
                    "courses_scraped": result.get("courses_scraped", 0),
                    "assignments_added": result.get("assignments_added", 0),
                    "assignments_updated": result.get("assignments_updated", 0),
                }

            self.supabase.table("sync_metadata").insert({
                "last_sync_at": datetime.now(timezone.utc).isoformat(),
                "last_sync_status": status,
                "last_sync_summary": summary,
                "last_sync_error": error,
            }).execute()

        except Exception as e:
            logger.error(f"Error saving sync metadata: {e}")


# Global sync service instance
sync_service = SyncService()
