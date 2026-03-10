"""
Canvas LMS API client.

Fetches assignments from BYU's Canvas instance using a personal access token.
Pure HTTP (requests library) — no Selenium needed.
"""

import html
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

# Maps Canvas submission_types to human-readable labels
SUBMISSION_TYPE_LABELS = {
    "online_upload":     "File Upload",
    "online_text_entry": "Text Entry",
    "online_url":        "Website URL",
    "online_quiz":       "Quiz",
    "discussion_topic":  "Discussion",
    "media_recording":   "Media Recording",
    "external_tool":     "External Tool",
    "none":              "No Submission",
    "not_graded":        "Not Graded",
    "on_paper":          "On Paper",
    "attendance":        "Attendance",
    "wiki_page":         "Page",
}


def _strip_html(text: str) -> str:
    """Strip HTML tags, decode entities, and collapse whitespace."""
    if not text:
        return ""
    # Remove style/script blocks entirely
    text = re.sub(r'<(style|script)[^>]*>.*?</\1>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Decode HTML entities (&nbsp; &amp; &lt; &#160; etc.)
    text = html.unescape(text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _map_submission_type(submission_types: list) -> str:
    """Map Canvas submission_types array to a human-readable assignment type."""
    if not submission_types:
        return "Assignment"
    primary = submission_types[0]
    return SUBMISSION_TYPE_LABELS.get(primary, primary.replace("_", " ").title())


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
            params = {}  # params are embedded in the next URL
            link_header = resp.headers.get("Link", "")
            for part in link_header.split(","):
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip().strip("<>")
                    break

        return results

    def get_courses(self) -> list[dict]:
        """Get active student courses for the current user.

        Filters to student enrollments only (excludes TA/teacher/observer roles)
        and only returns courses that are currently available.
        """
        url = f"{self.base_url}/api/v1/courses"
        params = {
            "enrollment_state": "active",
            "enrollment_type[]": "student",   # student only — exclude TA/teacher roles
            "per_page": "100",
        }
        courses = self._paginate(url, params)
        # Only return courses with an actual name (filter phantom enrollments)
        courses = [c for c in courses if c.get("name")]
        logger.info(f"Canvas: found {len(courses)} active student courses")
        return courses

    def get_assignments(self, course_id: int, course_name: str) -> list[dict]:
        """Get assignments for a course with full data including submission status.

        Uses include[]=submission to get current submission state per assignment.
        Due dates from Canvas are in UTC and are converted to Mountain Time.
        The API returns the student's effective due date (after any overrides/extensions).
        """
        url = f"{self.base_url}/api/v1/courses/{course_id}/assignments"
        params = {
            "include[]": ["submission", "overrides"],
            "per_page": "100",
            "order_by": "due_at",
        }

        try:
            raw_assignments = self._paginate(url, params)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code in (401, 403):
                logger.warning(f"Canvas: access denied for course {course_name} (id={course_id})")
                return []
            if e.response is not None and e.response.status_code == 404:
                logger.warning(f"Canvas: course not found {course_name} (id={course_id})")
                return []
            raise

        assignments = []
        for a in raw_assignments:
            # Skip unpublished or locked assignments
            if not a.get("published", True):
                continue

            status = self._map_status(a)

            # Parse due date — Canvas returns UTC; convert to Mountain Time.
            # When querying as a student, Canvas already applies the student's
            # effective due date (section overrides, individual extensions, etc.)
            due_date = None
            due_at = a.get("due_at")
            if due_at:
                try:
                    dt = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
                    due_date = dt.astimezone(MOUNTAIN).isoformat()
                except (ValueError, TypeError):
                    logger.warning(f"Canvas: could not parse due_at='{due_at}' for '{a.get('name')}'")

            # Extra credit: Canvas uses omit_from_final_grade
            is_extra_credit = bool(a.get("omit_from_final_grade"))

            # Clean description: strip HTML, decode entities, truncate
            raw_desc = a.get("description") or ""
            description = _strip_html(raw_desc)[:1000]

            # Normalize assignment type
            submission_types = a.get("submission_types") or []
            assignment_type = _map_submission_type(submission_types)

            # Points possible — None means ungraded
            points = a.get("points_possible")

            assignments.append({
                "title": a.get("name", "Untitled").strip(),
                "course_name": course_name,
                "due_date": due_date,
                "description": description,
                "link": a.get("html_url", ""),
                "status": status,
                "source": "canvas",
                "canvas_id": a.get("id"),
                "assignment_type": assignment_type,
                "is_extra_credit": is_extra_credit,
                "point_value": points,
            })

        logger.info(f"Canvas: {course_name} → {len(assignments)} assignments")
        return assignments

    def _map_status(self, assignment: dict) -> str:
        """Map Canvas submission state to app status."""
        if assignment.get("locked_for_user"):
            return "unavailable"

        submission = assignment.get("submission") or {}
        workflow = submission.get("workflow_state", "")

        # Submitted states — student has turned something in
        if workflow in ("submitted", "graded", "pending_review", "resubmitted"):
            return "submitted"

        # Late submission still counts as submitted
        if submission.get("late") and workflow not in ("unsubmitted", ""):
            return "submitted"

        return "not_started"

    def scrape_all_courses(self, progress_callback=None) -> list[dict]:
        """Fetch assignments from all active student courses.

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
            except Exception as e:
                logger.error(f"Canvas: error fetching {course_name}: {e}")

        logger.info(f"Canvas: total {len(all_assignments)} assignments across {len(courses)} courses")
        return all_assignments

    def update_database(self, assignments: list[dict], supabase_client=None, user_id: str = None) -> dict:
        """Upsert Canvas assignments into Supabase by canvas_id.

        Rules:
        - New assignments → status "newly_assigned" (unless already submitted)
        - Existing, not user-modified → update all fields; preserve in-progress status
          unless Canvas now says submitted/unavailable
        - Existing, user-modified → update metadata only (title, due_date, description,
          link, point_value, is_extra_credit) but never touch status or planning fields

        Args:
            assignments: List of assignment dicts from scrape_all_courses()
            supabase_client: Supabase client to reuse (prefer service-role key)
            user_id: The authenticated user's ID for RLS

        Returns:
            Dict with counts: {"new": N, "modified": N, "unchanged": N, "errors": N}
        """
        if supabase_client:
            supabase = supabase_client
        else:
            url = os.getenv("SUPABASE_URL")
            key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
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
                # Fetch existing record for this user
                query = supabase.table("assignments").select("id, status, is_modified").eq("canvas_id", canvas_id)
                if user_id:
                    query = query.eq("user_id", user_id)
                existing = query.execute()

                # Fields that always get updated (instructor-controlled, never user-editable)
                metadata_fields = {
                    "title":           a["title"],
                    "course_name":     a["course_name"],
                    "due_date":        a.get("due_date"),
                    "description":     a.get("description"),
                    "link":            a.get("link"),
                    "assignment_type": a.get("assignment_type"),
                    "point_value":     a.get("point_value"),   # always refresh — instructor may change
                    "is_extra_credit": a.get("is_extra_credit", False),
                    "last_scraped_at": now_iso,
                    "source":          "canvas",
                    "canvas_id":       canvas_id,
                }
                if user_id:
                    metadata_fields["user_id"] = user_id

                if existing.data:
                    record = existing.data[0]
                    current_status = record.get("status", "not_started")
                    canvas_status = a["status"]

                    if record.get("is_modified"):
                        # User has manually modified this assignment (status, notes, planned times, etc.)
                        # Refresh Canvas-controlled fields only — never touch status or planning
                        update_data = metadata_fields
                    else:
                        # Not user-modified — sync status from Canvas if it indicates completion
                        # but preserve user-tracked progress states (newly_assigned, in_progress)
                        if canvas_status in ("submitted", "unavailable"):
                            new_status = canvas_status
                        else:
                            # Keep whatever the student has tracked; only reset if it was
                            # forced to not_started and Canvas still says not_started
                            new_status = current_status if current_status in (
                                "newly_assigned", "not_started", "in_progress"
                            ) else "not_started"
                        update_data = {**metadata_fields, "status": new_status}

                    supabase.table("assignments").update(update_data).eq("id", record["id"]).execute()
                    counts["modified"] += 1

                else:
                    # New assignment — mark as newly_assigned so it gets highlighted
                    canvas_status = a["status"]
                    metadata_fields["status"] = "submitted" if canvas_status == "submitted" else "newly_assigned"
                    supabase.table("assignments").insert(metadata_fields).execute()
                    counts["new"] += 1

            except Exception as e:
                logger.error(f"Canvas DB error for canvas_id={canvas_id}: {e}")
                counts["errors"] += 1

        logger.info(f"Canvas DB update: {counts}")
        return counts
