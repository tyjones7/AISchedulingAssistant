"""
Learning Suite iCal feed client.

Fetches and parses LS iCal feeds — no Selenium, no Duo MFA required.
Each course exposes a public(ish) iCal URL that contains assignment due dates.

Available from iCal: title, due date (date-only), description, stable UID
Not available: points, submission status, direct links
"""

import os
import logging
import re
from datetime import datetime, timezone, date as _date
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo

import requests
from icalendar import Calendar
from supabase import create_client

logger = logging.getLogger(__name__)

MOUNTAIN = ZoneInfo("America/Denver")

# Keywords for inferring assignment type from title
_EXAM_RE = re.compile(r'\b(exam|midterm|final|test)\b', re.IGNORECASE)
_QUIZ_RE = re.compile(r'\bquiz\b', re.IGNORECASE)
_READING_RE = re.compile(r'\b(reading|read|chapter)\b', re.IGNORECASE)
_DISCUSSION_RE = re.compile(r'\b(discussion|discussion board|db)\b', re.IGNORECASE)

# Patterns that identify non-assignment calendar events (class sessions, office hours, etc.)
_NON_ASSIGNMENT_RE = re.compile(
    r'^\*+\s*no\s+class|^\*+|'           # ***NO CLASS*** or any ***-prefixed marker
    r'^session\s+\d+[:\s]|'               # Session 21: ... or Session 3 ...
    r'\boffice\s+hours?\b|'               # Office Hours / Office Hour
    r'\bta\s+hours?\b|'                   # TA Hours
    r'\blab\s+section\b|'                 # Lab Section
    r'^class\s+(meeting|session)\b',      # Class Meeting / Class Session
    re.IGNORECASE,
)


def _extract_course_id(url: str) -> str | None:
    """Extract courseID query param from an LS iCal feed URL."""
    try:
        qs = parse_qs(urlparse(url).query)
        vals = qs.get("courseID") or qs.get("courseid") or qs.get("CourseID")
        return vals[0] if vals else None
    except Exception:
        return None


def _infer_assignment_type(title: str) -> str:
    """Infer assignment type from title keywords."""
    if _EXAM_RE.search(title):
        return "Exam"
    if _QUIZ_RE.search(title):
        return "Quiz"
    if _READING_RE.search(title):
        return "Reading"
    if _DISCUSSION_RE.search(title):
        return "Discussion"
    return "Assignment"


def _to_eod_mountain(dtstart) -> str | None:
    """Convert a DTSTART value (date or datetime) to end-of-day Mountain Time ISO string."""
    if dtstart is None:
        return None

    # icalendar returns either a date or datetime object
    if isinstance(dtstart, datetime):
        # Already a datetime — convert to Mountain Time
        if dtstart.tzinfo is None:
            dtstart = dtstart.replace(tzinfo=MOUNTAIN)
        mt = dtstart.astimezone(MOUNTAIN)
        # Use end-of-day if it looks like midnight (all-day event stored as datetime)
        if mt.hour == 0 and mt.minute == 0 and mt.second == 0:
            mt = mt.replace(hour=23, minute=59, second=59)
        return mt.isoformat()
    elif isinstance(dtstart, _date):
        # Date-only value → end-of-day Mountain Time
        mt_eod = datetime(dtstart.year, dtstart.month, dtstart.day,
                          23, 59, 59, tzinfo=MOUNTAIN)
        return mt_eod.isoformat()
    return None


def fetch_and_parse(url: str, course_name: str) -> list[dict]:
    """Fetch an iCal feed URL and return a list of assignment dicts.

    Args:
        url: Full iCal feed URL (e.g. https://learningsuite.byu.edu/iCalFeed/ical.php?courseID=...)
        course_name: Human-readable course name to attach to each assignment

    Returns:
        List of assignment dicts compatible with the assignments table schema.
        Missing SUMMARY or DTSTART events are skipped.
    """
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"iCal fetch failed for {url}: {e}")
        raise

    cal = Calendar.from_ical(resp.content)
    assignments = []

    for component in cal.walk('VEVENT'):
        summary = component.get('SUMMARY')
        dtstart_prop = component.get('DTSTART')

        # Skip events without a title or start date
        if not summary or dtstart_prop is None:
            continue

        # Normalize whitespace (LS occasionally wraps long titles)
        title = re.sub(r'\s+', ' ', str(summary)).strip()
        if not title:
            continue

        # Skip non-assignment events (class sessions, office hours, TA hours, etc.)
        if _NON_ASSIGNMENT_RE.search(title):
            logger.debug(f"iCal: skipping non-assignment event: {title!r}")
            continue

        dtstart_val = dtstart_prop.dt if hasattr(dtstart_prop, 'dt') else dtstart_prop
        due_date = _to_eod_mountain(dtstart_val)
        if not due_date:
            continue

        # Description — strip whitespace, truncate
        desc_raw = component.get('DESCRIPTION')
        description = str(desc_raw).strip()[:1000] if desc_raw else None

        # UID — stable identifier for deduplication
        uid = component.get('UID')
        ls_ical_uid = str(uid).strip() if uid else None

        assignments.append({
            "title": title,
            "course_name": course_name,
            "due_date": due_date,
            "description": description,
            "link": None,
            "source": "learning_suite",
            "ls_ical_uid": ls_ical_uid,
            "assignment_type": _infer_assignment_type(title),
            "point_value": None,
            "is_extra_credit": False,
        })

    logger.info(f"iCal: {course_name} → {len(assignments)} events from {url}")
    return assignments


def update_database(assignments: list[dict], supabase_client=None, user_id: str = None, feed_url: str = None) -> dict:
    """Upsert iCal assignments into Supabase by ls_ical_uid.

    Rules mirror canvas_client.update_database():
    - New assignments → status "newly_assigned"
    - Existing, not user-modified → update metadata fields
    - Existing, user-modified → update metadata only, never touch status/planning

    Args:
        assignments: List of dicts from fetch_and_parse()
        supabase_client: Supabase client (prefer service-role key)
        user_id: Authenticated user ID for RLS scoping

    Returns:
        Dict with counts: {"new": N, "modified": N, "unchanged": N, "errors": N}
    """
    if supabase_client:
        supabase = supabase_client
    else:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
        if not url or not key:
            logger.error("iCal: missing Supabase credentials")
            return {"new": 0, "modified": 0, "unchanged": 0, "errors": len(assignments)}
        supabase = create_client(url, key)

    counts = {"new": 0, "modified": 0, "unchanged": 0, "errors": 0, "new_items": []}
    now_iso = datetime.now(timezone.utc).isoformat()

    # Bulk-fetch existing records for this user that have ls_ical_uid set
    # to avoid N+1 queries
    uids = [a["ls_ical_uid"] for a in assignments if a.get("ls_ical_uid")]
    existing_by_uid: dict[str, dict] = {}
    if uids and user_id:
        try:
            resp = supabase.table("assignments").select(
                "id, status, is_modified, ls_ical_uid"
            ).eq("user_id", user_id).in_("ls_ical_uid", uids).execute()
            for row in (resp.data or []):
                if row.get("ls_ical_uid"):
                    existing_by_uid[row["ls_ical_uid"]] = row
        except Exception as e:
            logger.warning(f"iCal: bulk fetch failed, falling back to per-row queries: {e}")

    for a in assignments:
        ls_ical_uid = a.get("ls_ical_uid")
        if not ls_ical_uid:
            counts["errors"] += 1
            continue

        try:
            metadata_fields = {
                "title":           a["title"],
                "course_name":     a["course_name"],
                "due_date":        a.get("due_date"),
                "description":     a.get("description"),
                "assignment_type": a.get("assignment_type"),
                "last_scraped_at": now_iso,
                "source":          "learning_suite",
                "ls_ical_uid":     ls_ical_uid,
            }
            if user_id:
                metadata_fields["user_id"] = user_id

            # Use bulk-fetched result if available, else fall back to query
            record = existing_by_uid.get(ls_ical_uid)
            if record is None and not existing_by_uid:
                # Bulk fetch wasn't attempted (no user_id or empty uids)
                query = supabase.table("assignments").select(
                    "id, status, is_modified"
                ).eq("ls_ical_uid", ls_ical_uid)
                if user_id:
                    query = query.eq("user_id", user_id)
                result = query.execute()
                record = result.data[0] if result.data else None

            if record:
                if record.get("is_modified"):
                    update_data = metadata_fields
                else:
                    current_status = record.get("status", "not_started")
                    keep_status = current_status if current_status in (
                        "newly_assigned", "not_started", "in_progress"
                    ) else "not_started"
                    update_data = {**metadata_fields, "status": keep_status}

                supabase.table("assignments").update(update_data).eq(
                    "id", record["id"]
                ).execute()
                counts["modified"] += 1
            else:
                metadata_fields["status"] = "newly_assigned"
                metadata_fields["classification_confirmed"] = False
                inserted = supabase.table("assignments").insert(metadata_fields).execute()
                counts["new"] += 1
                if inserted.data:
                    row = inserted.data[0]
                    counts["new_items"].append({
                        "id": row["id"],
                        "uid": ls_ical_uid,
                        "title": a["title"],
                    })

        except Exception as e:
            logger.error(f"iCal DB error for uid={ls_ical_uid}: {e}")
            counts["errors"] += 1

    # ---- Stale cleanup ----
    # Delete DB assignments for this feed whose UID is no longer in the current batch.
    # We match by courseID embedded in the UID (format: {eventId}{courseID}@ctl.byu.edu).
    if feed_url and user_id and uids:
        course_id = _extract_course_id(feed_url)
        if course_id:
            try:
                # Fetch all user assignments whose ls_ical_uid contains this courseID
                all_resp = supabase.table("assignments").select(
                    "id, ls_ical_uid"
                ).eq("user_id", user_id).like("ls_ical_uid", f"%{course_id}%").execute()

                current_uid_set = set(uids)
                stale_ids = [
                    row["id"] for row in (all_resp.data or [])
                    if row.get("ls_ical_uid") and row["ls_ical_uid"] not in current_uid_set
                ]
                if stale_ids:
                    supabase.table("assignments").delete().in_("id", stale_ids).execute()
                    counts["deleted"] = len(stale_ids)
                    logger.info(f"iCal: deleted {len(stale_ids)} stale assignments for courseID={course_id}")
            except Exception as e:
                logger.warning(f"iCal: stale cleanup failed for courseID={course_id}: {e}")

    logger.info(f"iCal DB update: {counts}")
    return counts
