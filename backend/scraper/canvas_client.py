"""
Canvas LMS API client.

Fetches assignments from BYU's Canvas instance using a personal access token.
Pure HTTP (requests library) — no Selenium needed.
"""

import os
import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

logger = logging.getLogger(__name__)

CANVAS_BASE_URL = "https://byu.instructure.com"
MOUNTAIN = ZoneInfo("America/Denver")


def _strip_html(text: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


class CanvasClient:
    """Client for the Canvas LMS REST API."""

    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.base_url = CANVAS_BASE_URL

    def _paginate(self, url: str, params: dict | None = None) -> list:
        """Handle Canvas Link-header pagination. Returns all items across pages."""
        results = []
        params = params or {}

        while url:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                results.extend(data)
            else:
                logger.warning(f"Canvas: expected list but got {type(data).__name__}")
                break

            # Follow next page from Link header
            url = None
            params = {}  # params are already in the next URL
            link_header = resp.headers.get("Link", "")
            for part in link_header.split(","):
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip().strip("<>")
                    break

        return results

    def get_courses(self) -> list[dict]:
        """Get active courses for the current user."""
        url = f"{self.base_url}/api/v1/users/self/courses"
        params = {"enrollment_state": "active", "per_page": "100"}
        courses = self._paginate(url, params)
        logger.info(f"Canvas: found {len(courses)} active courses")
        return courses

    def get_assignments(self, course_id: int, course_name: str) -> list[dict]:
        """Get assignments for a course, with submission status."""
        url = f"{self.base_url}/api/v1/courses/{course_id}/assignments"
        params = {"include[]": "submission", "per_page": "100"}

        try:
            raw_assignments = self._paginate(url, params)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                logger.warning(f"Canvas: unauthorized for course {course_name} (id={course_id})")
                return []
            raise

        assignments = []
        for a in raw_assignments:
            # Skip unpublished assignments
            if not a.get("published", True):
                continue

            # Map submission state to app status
            status = self._map_status(a)

            # Parse due date
            due_date = None
            if a.get("due_at"):
                try:
                    dt = datetime.fromisoformat(a["due_at"].replace("Z", "+00:00"))
                    due_date = dt.astimezone(MOUNTAIN).isoformat()
                except (ValueError, TypeError):
                    pass

            assignments.append({
                "title": a.get("name", "Untitled"),
                "course_name": course_name,
                "due_date": due_date,
                "description": _strip_html(a.get("description") or "")[:500],
                "link": a.get("html_url", ""),
                "status": status,
                "source": "canvas",
                "canvas_id": a.get("id"),
                "assignment_type": a.get("submission_types", ["unknown"])[0] if a.get("submission_types") else "unknown",
            })

        return assignments

    def _map_status(self, assignment: dict) -> str:
        """Map Canvas submission state to app status."""
        if assignment.get("locked_for_user"):
            return "unavailable"

        submission = assignment.get("submission") or {}
        workflow = submission.get("workflow_state", "")

        if workflow in ("submitted", "graded"):
            return "submitted"

        return "not_started"

    def scrape_all_courses(self, progress_callback=None) -> list[dict]:
        """Fetch assignments from all active courses.

        Args:
            progress_callback: Optional fn(current, total, course_name)

        Returns:
            Flat list of assignment dicts
        """
        courses = self.get_courses()
        all_assignments = []

        if progress_callback:
            progress_callback(0, len(courses), "")

        for i, course in enumerate(courses, 1):
            course_name = course.get("name", f"Course {course.get('id')}")

            if progress_callback:
                progress_callback(i, len(courses), course_name)

            try:
                assignments = self.get_assignments(course["id"], course_name)
                all_assignments.extend(assignments)
                logger.info(f"Canvas: {course_name} -> {len(assignments)} assignments")
            except Exception as e:
                logger.error(f"Canvas: error fetching {course_name}: {e}")

        logger.info(f"Canvas: total {len(all_assignments)} assignments from {len(courses)} courses")
        return all_assignments

    def update_database(self, assignments: list[dict], supabase_client=None) -> dict:
        """Upsert Canvas assignments into Supabase by canvas_id.

        Args:
            assignments: List of assignment dicts from scrape_all_courses()
            supabase_client: Optional Supabase client to reuse

        Returns:
            Dict with counts: {"new": N, "modified": N, "unchanged": N, "errors": N}
        """
        if supabase_client:
            supabase = supabase_client
        else:
            url = os.getenv("SUPABASE_URL")
            key = os.getenv("SUPABASE_KEY")
            if not url or not key:
                logger.error("Canvas: missing Supabase credentials")
                return {"new": 0, "modified": 0, "unchanged": 0, "errors": len(assignments)}
            supabase = create_client(url, key)
        counts = {"new": 0, "modified": 0, "unchanged": 0, "errors": 0}
        now_iso = datetime.now(timezone.utc).isoformat()

        for a in assignments:
            canvas_id = a.get("canvas_id")
            if not canvas_id:
                counts["errors"] += 1
                continue

            try:
                # Check if assignment already exists
                existing = supabase.table("assignments").select("*").eq(
                    "canvas_id", canvas_id
                ).execute()

                row = {
                    "title": a["title"],
                    "course_name": a["course_name"],
                    "due_date": a.get("due_date"),
                    "description": a.get("description"),
                    "link": a.get("link"),
                    "source": "canvas",
                    "canvas_id": canvas_id,
                    "assignment_type": a.get("assignment_type"),
                    "last_scraped_at": now_iso,
                }

                if existing.data:
                    # Update existing — but don't overwrite user-modified status
                    record = existing.data[0]
                    if record.get("is_modified"):
                        # Only update non-user fields
                        update_data = {
                            "title": row["title"],
                            "course_name": row["course_name"],
                            "due_date": row["due_date"],
                            "description": row["description"],
                            "link": row["link"],
                            "last_scraped_at": now_iso,
                        }
                    else:
                        update_data = {**row, "status": a["status"]}

                    supabase.table("assignments").update(update_data).eq(
                        "id", record["id"]
                    ).execute()
                    counts["modified"] += 1
                else:
                    # Insert new
                    row["status"] = a["status"]
                    supabase.table("assignments").insert(row).execute()
                    counts["new"] += 1

            except Exception as e:
                logger.error(f"Canvas DB error for canvas_id={canvas_id}: {e}")
                counts["errors"] += 1

        logger.info(f"Canvas DB: {counts}")
        return counts
