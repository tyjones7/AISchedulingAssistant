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
            "total_courses": task.total_courses,
            "current_course": task.current_course,
            "current_course_name": task.current_course_name,
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
        """Run the sync process in a background thread.

        Includes resilience features:
        - Passes web storage data alongside cookies for better session persistence
        - If scraping fails with a session error, attempts to re-inject cookies
          and retry from the failed point (not from scratch)
        """
        task = self._tasks.get(task_id)
        if not task:
            return

        scraper = None
        should_close_scraper = False

        ls_authenticated = auth_store.is_authenticated()
        canvas_token = canvas_auth_store.get_token()

        if not ls_authenticated and not canvas_token:
            with self._task_lock:
                task.status = SyncStatus.FAILED
                task.error = "Not authenticated. Please connect Learning Suite or Canvas first."
                task.message = f"Sync failed: {task.error}"
                task.completed_at = datetime.now(timezone.utc)
            self._save_sync_metadata(task_id, "failed", None, task.error)
            return

        try:
            # ---- Learning Suite sync ----
            if ls_authenticated:
                self._update_task(task_id, SyncStatus.CHECKING_SESSION, "Checking authentication...")
                logger.info(f"Sync [{task_id[:8]}] - Checking for authenticated session...")

                cookies, base_url = auth_store.get_session_data()
                local_storage, session_storage = auth_store.get_web_storage()

                if cookies and base_url:
                    logger.info(f"Sync [{task_id[:8]}] - Found stored cookies ({len(cookies)}), creating headless browser...")
                    if local_storage:
                        logger.info(f"Sync [{task_id[:8]}] - Also found {len(local_storage)} localStorage items")
                    if session_storage:
                        logger.info(f"Sync [{task_id[:8]}] - Also found {len(session_storage)} sessionStorage items")

                    self._update_task(task_id, SyncStatus.CHECKING_SESSION, "Starting headless browser...")

                    scraper = LearningSuiteScraper(headless=True)
                    scraper._setup_driver()
                    should_close_scraper = True

                    self._update_task(task_id, SyncStatus.CHECKING_SESSION, "Restoring session...")
                    if not scraper.inject_cookies(cookies, base_url,
                                                  local_storage=local_storage,
                                                  session_storage=session_storage):
                        scraper.close()
                        scraper = None
                        auth_store.clear_authentication()
                        logger.warning(f"Sync [{task_id[:8]}] - LS session expired")
                    else:
                        self._update_task(task_id, SyncStatus.SCRAPING, "Session restored, scraping...")
                else:
                    # Fallback: check if there's a live authenticated scraper
                    existing = auth_store.get_authenticated_scraper()

                    if existing and existing.driver:
                        scraper = existing
                        logger.info(f"Sync [{task_id[:8]}] - Using existing authenticated session")
                        self._update_task(task_id, SyncStatus.SCRAPING, "Using authenticated session...")
                        should_close_scraper = False
                    else:
                        logger.info(f"Sync [{task_id[:8]}] - No session data, trying headless...")
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
                            scraper = None
                            logger.warning(f"Sync [{task_id[:8]}] - LS headless check failed")

                if scraper:
                    # Define progress callback that updates task fields thread-safely
                    def progress_callback(current, total, course_name):
                        with self._task_lock:
                            task.total_courses = total
                            task.current_course = current
                            task.current_course_name = course_name
                            if current == 0:
                                task.message = f"Found {total} courses, starting..."
                            else:
                                task.message = f"Scraped {course_name} ({current}/{total})"
                        logger.info(f"Sync [{task_id[:8]}] - Course {current}/{total}: {course_name}")

                    self._update_task(task_id, SyncStatus.SCRAPING, "Scraping assignments from courses...")
                    try:
                        assignments = scraper.scrape_all_courses(
                            progress_callback=progress_callback,
                            save_per_course=True
                        )
                    except Exception as scrape_error:
                        error_msg = str(scrape_error)
                        logger.error(f"Sync [{task_id[:8]}] - Scraping error: {error_msg}")

                        is_session_error = any(indicator in error_msg.lower() for indicator in [
                            "session expired", "please sign in", "cas.byu.edu",
                            "authentication", "login", "redirected"
                        ])

                        if is_session_error and cookies and base_url:
                            logger.info(f"Sync [{task_id[:8]}] - Session error detected, attempting recovery...")
                            self._update_task(task_id, SyncStatus.CHECKING_SESSION, "Session lost, attempting recovery...")

                            try:
                                scraper.close()
                            except:
                                pass

                            scraper = LearningSuiteScraper(headless=True)
                            scraper._setup_driver()
                            should_close_scraper = True

                            if scraper.inject_cookies(cookies, base_url,
                                                      local_storage=local_storage,
                                                      session_storage=session_storage):
                                logger.info(f"Sync [{task_id[:8]}] - Recovery successful, retrying scrape...")
                                self._update_task(task_id, SyncStatus.SCRAPING, "Recovered, retrying scrape...")
                                assignments = scraper.scrape_all_courses(
                                    progress_callback=progress_callback,
                                    save_per_course=True
                                )
                            else:
                                auth_store.clear_authentication()
                                raise ValueError("Session expired during sync and could not be recovered. Please sign in again.")
                        else:
                            raise

                    logger.info(f"Sync [{task_id[:8]}] - Scraped {len(assignments)} LS assignments")

                    # Aggregate per-course DB results
                    total_new = 0
                    total_modified = 0
                    for db_result in getattr(scraper, '_per_course_db_results', []):
                        total_new += db_result.get("new", 0)
                        total_modified += db_result.get("modified", 0)

                    with self._task_lock:
                        courses = set(a.get("course_name") for a in assignments if a.get("course_name"))
                        task.courses_scraped = len(courses)
                        task.assignments_added = total_new
                        task.assignments_updated = total_modified

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
                    canvas_result = canvas.update_database(canvas_assignments)

                    with self._task_lock:
                        task.assignments_added += canvas_result.get("new", 0)
                        task.assignments_updated += canvas_result.get("modified", 0)
                        canvas_courses = set(a.get("course_name") for a in canvas_assignments if a.get("course_name"))
                        task.courses_scraped += len(canvas_courses)

                    logger.info(f"Sync [{task_id[:8]}] - Canvas: {canvas_result}")
                except Exception as e:
                    logger.error(f"Sync [{task_id[:8]}] - Canvas sync error: {e}")
                    if not ls_authenticated:
                        raise  # Canvas-only sync: propagate error

            # Build result summary for metadata
            result = {
                "courses_scraped": task.courses_scraped,
                "assignments_added": task.assignments_added,
                "assignments_updated": task.assignments_updated,
            }

            self._update_task(task_id, SyncStatus.UPDATING_DB, "Updating sync metadata...")
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
