import os
import json
import logging
from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Literal, Optional
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from supabase import create_client

from sync_service import sync_service
import canvas_auth_store
import ai_service

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


_ALLOWED_ICAL_HOSTS = {
    "learningsuite.byu.edu",
    "calendar.google.com",
    "outlook.live.com",
    "outlook.office365.com",
    "apple.com",
    "icloud.com",
}

def _validate_ical_url(url: str) -> None:
    """Raise HTTPException if the URL is not a safe, allowed iCal source."""
    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL format")
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="iCal URL must use HTTPS")
    host = parsed.hostname or ""
    if not any(host == allowed or host.endswith("." + allowed) for allowed in _ALLOWED_ICAL_HOSTS):
        raise HTTPException(
            status_code=400,
            detail=f"URL host '{host}' is not an allowed iCal source. "
                   "Supported: Learning Suite, Google Calendar, Outlook, iCloud."
        )


class StatusUpdate(BaseModel):
    status: Literal['newly_assigned', 'not_started', 'in_progress', 'submitted', 'unavailable']


class AssignmentUpdate(BaseModel):
    status: Optional[Literal['newly_assigned', 'not_started', 'in_progress', 'submitted', 'unavailable']] = None
    estimated_minutes: Optional[int] = None
    planned_start: Optional[str] = None
    planned_end: Optional[str] = None
    notes: Optional[str] = None
    title: Optional[str] = None
    course_name: Optional[str] = None
    due_date: Optional[str] = None
    task_type: Optional[Literal['assignment', 'exam_prep', 'reading', 'personal', 'other']] = None


class AssignmentCreate(BaseModel):
    title: str
    course_name: str
    due_date: str  # ISO datetime string
    point_value: Optional[float] = None
    assignment_type: Optional[str] = None
    task_type: Optional[Literal['assignment', 'exam_prep', 'reading', 'personal', 'other']] = None
    estimated_minutes: Optional[int] = None
    notes: Optional[str] = None


class TimeBlockUpdate(BaseModel):
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    status: Optional[Literal['planned', 'completed', 'skipped']] = None


class SyncStartResponse(BaseModel):
    task_id: str
    message: str


class SyncStatusResponse(BaseModel):
    task_id: str
    status: str
    message: str
    error: Optional[str] = None
    started_at: str
    completed_at: Optional[str] = None
    assignments_added: int = 0
    assignments_updated: int = 0
    courses_scraped: int = 0
    total_courses: int = 0
    current_course: int = 0
    current_course_name: str = ""


class LoginRequest(BaseModel):
    netid: str
    password: str


class CanvasTokenRequest(BaseModel):
    token: str


# ============== AI MODELS ==============

class AISuggestion(BaseModel):
    id: str
    assignment_id: str
    priority_score: int
    suggested_start: Optional[str] = None
    rationale: Optional[str] = None
    estimated_minutes: Optional[int] = None
    generated_at: str


class AISuggestionsResponse(BaseModel):
    suggestions: list[AISuggestion]
    generated_at: str


class AIBriefingResponse(BaseModel):
    briefing: str
    generated_at: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AIChatRequest(BaseModel):
    messages: list[ChatMessage]


class AIApplyPlanRequest(BaseModel):
    messages: list[ChatMessage]


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict  # {p256dh: str, auth: str}


class LSICalFeedCreate(BaseModel):
    url: str
    course_name: str


class ExternalCalendarCreate(BaseModel):
    url: str
    label: str = "My Calendar"


class LSICalFeedUpdate(BaseModel):
    url: Optional[str] = None
    course_name: Optional[str] = None


class UserPreferences(BaseModel):
    id: Optional[str] = None
    study_time: Literal["morning", "afternoon", "evening", "night"] = "evening"
    session_length_minutes: int = 60
    advance_days: int = 2
    work_style: Literal["spread_out", "batch"] = "spread_out"
    involvement_level: Literal["proactive", "balanced", "prompt_only"] = "balanced"
    weekly_schedule: Optional[list] = None
    work_start: Optional[str] = "08:00"
    work_end: Optional[str] = "22:00"
    student_context: Optional[str] = ""
    course_colors: Optional[dict] = None


class UserPreferencesUpdate(BaseModel):
    study_time: Optional[Literal["morning", "afternoon", "evening", "night"]] = None
    session_length_minutes: Optional[int] = None
    advance_days: Optional[int] = None
    work_style: Optional[Literal["spread_out", "batch"]] = None
    involvement_level: Optional[Literal["proactive", "balanced", "prompt_only"]] = None
    weekly_schedule: Optional[list] = None
    work_start: Optional[str] = None
    work_end: Optional[str] = None
    student_context: Optional[str] = None
    course_colors: Optional[dict] = None


load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "Missing required environment variables: "
        + ("SUPABASE_URL " if not SUPABASE_URL else "")
        + ("SUPABASE_KEY" if not SUPABASE_KEY else "")
        + ". Check your .env file or environment."
    )

# Anon client — used only as a fallback if service key is not set
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Service-role client — bypasses RLS; used for all backend DB operations
supabase_service = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY) if SUPABASE_SERVICE_KEY else supabase

app = FastAPI(title="AI Scheduling Assistant API", version="1.0.0")

logger.info("FastAPI app initialized")

# Configure CORS to allow requests from the React frontend
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in CORS_ORIGIN.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============== JWT AUTH DEPENDENCY ==============

async def get_current_user(authorization: str = Header(None)) -> str:
    """Verify Supabase JWT and return the user_id using Supabase's auth API."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization.split(" ", 1)[1]
    try:
        response = supabase.auth.get_user(token)
        if not response.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return response.user.id
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {e}")


@app.get("/")
def read_root():
    return {"message": "Hello World"}


@app.get("/ping")
def ping():
    return {"status": "ok", "message": "Backend is connected!"}


@app.post("/auth/logout")
def logout(user_id: str = Depends(get_current_user)):
    """Clear Canvas token on logout."""
    logger.info(f"POST /auth/logout user={user_id[:8]}")
    canvas_auth_store.clear_token(user_id)
    return {"success": True, "message": "Logged out"}


# ============== CANVAS AUTH ROUTES ==============

@app.post("/auth/canvas-token")
def set_canvas_token(req: CanvasTokenRequest, user_id: str = Depends(get_current_user)):
    """Validate and store a Canvas API token."""
    token = req.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token is required")

    valid, result = canvas_auth_store.validate_token(token)
    if not valid:
        raise HTTPException(status_code=401, detail=result)

    canvas_auth_store.set_token(user_id, token, result)
    logger.info(f"POST /auth/canvas-token user={user_id[:8]} - Connected as {result}")
    return {"success": True, "user_name": result}


@app.get("/auth/canvas-status")
def canvas_status(user_id: str = Depends(get_current_user)):
    """Check if Canvas is connected."""
    return {
        "connected": canvas_auth_store.is_connected(user_id),
        "user_name": canvas_auth_store.get_user_name(user_id),
    }


@app.delete("/auth/canvas-token")
def delete_canvas_token(user_id: str = Depends(get_current_user)):
    """Disconnect Canvas."""
    canvas_auth_store.clear_token(user_id)
    logger.info(f"DELETE /auth/canvas-token user={user_id[:8]}")
    return {"success": True}


@app.get("/assignments")
def get_assignments(
    exclude_past_submitted: bool = Query(default=False),
    include_course_content: bool = Query(default=False),
    user_id: str = Depends(get_current_user),
):
    """Get assignments. Filters out course_content items by default.

    Pass include_course_content=true to include class topics, reading guides, etc.
    Pass exclude_past_submitted=true to skip submitted past-due items.
    """
    query = supabase_service.table("assignments").select("*").eq("user_id", user_id).order("due_date")
    if not include_course_content:
        query = query.neq("content_type", "course_content")
    if exclude_past_submitted:
        now_iso = datetime.now(timezone.utc).isoformat()
        query = query.or_(f"status.neq.submitted,due_date.gte.{now_iso}")
    response = query.execute()
    return {"assignments": response.data}


# IMPORTANT: Static routes must come BEFORE parameterized routes
@app.get("/assignments/stats/summary")
def get_assignment_stats(user_id: str = Depends(get_current_user)):
    """Get assignment statistics for the dashboard."""
    from zoneinfo import ZoneInfo

    response = supabase_service.table("assignments").select("*").eq("user_id", user_id).execute()
    assignments = response.data or []

    mountain = ZoneInfo("America/Denver")
    now_mt = datetime.now(mountain)
    today_mt = datetime(now_mt.year, now_mt.month, now_mt.day, tzinfo=mountain)
    week_end_mt = today_mt + timedelta(days=7)

    total = len(assignments)
    submitted = sum(1 for a in assignments if a.get("status") == "submitted")

    # Due this week (not submitted) - compare in Mountain Time
    due_this_week = 0
    for a in assignments:
        if a.get("status") != "submitted" and a.get("due_date"):
            try:
                due = datetime.fromisoformat(a["due_date"].replace("Z", "+00:00"))
                if due.tzinfo is None:
                    due = due.replace(tzinfo=mountain)
                # Convert to Mountain Time for comparison
                due_mt = due.astimezone(mountain)
                due_date_only = datetime(due_mt.year, due_mt.month, due_mt.day, tzinfo=mountain)
                if today_mt <= due_date_only < week_end_mt:
                    due_this_week += 1
            except (ValueError, TypeError):
                pass

    # Calculate completion rate
    completion_rate = round((submitted / total * 100) if total > 0 else 0)

    return {
        "total": total,
        "submitted": submitted,
        "due_this_week": due_this_week,
        "completion_rate": completion_rate,
    }


@app.post("/assignments")
def create_assignment(
    data: AssignmentCreate,
    user_id: str = Depends(get_current_user),
):
    """Manually create an assignment."""
    insert_data = {
        "user_id": user_id,
        "title": data.title,
        "course_name": data.course_name,
        "due_date": data.due_date,
        "status": "not_started",
        "source": "manual",
        "is_modified": True,
        "last_scraped_at": datetime.now(timezone.utc).isoformat(),
    }
    if data.point_value is not None:
        insert_data["point_value"] = data.point_value
    if data.assignment_type:
        insert_data["assignment_type"] = data.assignment_type
    if data.task_type:
        insert_data["task_type"] = data.task_type
    if data.estimated_minutes:
        insert_data["estimated_minutes"] = data.estimated_minutes
    if data.notes:
        insert_data["notes"] = data.notes

    response = supabase_service.table("assignments").insert(insert_data).execute()

    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to create assignment")

    return {"assignment": response.data[0]}


@app.get("/assignments/{assignment_id}")
def get_assignment(assignment_id: str, user_id: str = Depends(get_current_user)):
    """Get a single assignment by ID."""
    response = supabase_service.table("assignments").select("*").eq("id", assignment_id).eq("user_id", user_id).execute()

    if not response.data:
        raise HTTPException(status_code=404, detail="Assignment not found")

    return {"assignment": response.data[0]}


@app.patch("/assignments/{assignment_id}")
def update_assignment(
    assignment_id: str,
    update: AssignmentUpdate,
    user_id: str = Depends(get_current_user),
):
    """Update assignment fields including status and planning data."""
    # Build update dict with only provided fields
    update_data = {}

    if update.status is not None:
        update_data["status"] = update.status
        if update.status == "submitted":
            update_data["submitted_at"] = datetime.now(timezone.utc).isoformat()
    if update.estimated_minutes is not None:
        update_data["estimated_minutes"] = update.estimated_minutes
    if update.planned_start is not None:
        update_data["planned_start"] = update.planned_start
    if update.planned_end is not None:
        update_data["planned_end"] = update.planned_end
    if update.notes is not None:
        update_data["notes"] = update.notes
    if update.title is not None:
        update_data["title"] = update.title
    if update.course_name is not None:
        update_data["course_name"] = update.course_name
    if update.due_date is not None:
        update_data["due_date"] = update.due_date
    if update.task_type is not None:
        update_data["task_type"] = update.task_type

    if update.estimated_minutes is not None and not (1 <= update.estimated_minutes <= 1440):
        raise HTTPException(status_code=422, detail="estimated_minutes must be between 1 and 1440")

    # Allow clearing planning fields with empty string
    if update.planned_start == "":
        update_data["planned_start"] = None
    if update.planned_end == "":
        update_data["planned_end"] = None
    if update.notes == "":
        update_data["notes"] = None

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    response = supabase_service.table("assignments").update(
        update_data
    ).eq("id", assignment_id).eq("user_id", user_id).execute()

    if not response.data:
        raise HTTPException(status_code=404, detail="Assignment not found")

    return {"assignment": response.data[0]}


@app.delete("/assignments/{assignment_id}", status_code=204)
def delete_assignment(assignment_id: str, user_id: str = Depends(get_current_user)):
    """Permanently delete an assignment and all its time blocks."""
    result = supabase_service.table("assignments").delete().eq(
        "id", assignment_id
    ).eq("user_id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Assignment not found")


@app.post("/assignments/dismiss-overdue")
def dismiss_overdue_assignments(user_id: str = Depends(get_current_user)):
    """Mark all past-due non-submitted assignments as submitted.

    Used to bulk-clear the overdue list when the scraper misclassified items
    the student has already completed.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    response = (
        supabase_service.table("assignments")
        .update({"status": "submitted", "is_modified": True})
        .eq("user_id", user_id)
        .lt("due_date", now_iso)
        .in_("status", ["not_started", "newly_assigned", "in_progress"])
        .execute()
    )
    count = len(response.data) if response.data else 0
    return {"dismissed": count}


# ============== SYNC ROUTES ==============
# These handle Learning Suite synchronization

@app.post("/sync/start", response_model=SyncStartResponse)
def start_sync(user_id: str = Depends(get_current_user)):
    """Start a new Learning Suite sync.

    Returns immediately with a task_id that can be polled for status.
    """
    logger.info(f"POST /sync/start user={user_id[:8]}")
    task_id, error = sync_service.start_sync(user_id)

    if error:
        logger.warning(f"POST /sync/start - Rejected: {error}")
        raise HTTPException(status_code=409, detail=error)

    logger.info(f"POST /sync/start - Created task: {task_id}")
    return SyncStartResponse(task_id=task_id, message="Sync started")


@app.get("/sync/status/{task_id}", response_model=SyncStatusResponse)
def get_sync_status(task_id: str, user_id: str = Depends(get_current_user)):
    """Get the status of a sync task.

    Poll this endpoint every few seconds to track sync progress.
    """
    logger.debug(f"GET /sync/status/{task_id}")
    status = sync_service.get_status(task_id)

    if not status:
        logger.warning(f"GET /sync/status/{task_id} - Task not found")
        raise HTTPException(status_code=404, detail="Task not found")

    logger.debug(f"GET /sync/status/{task_id} - Status: {status.get('status')}")
    return SyncStatusResponse(**status)


@app.get("/sync/last")
def get_last_sync(user_id: str = Depends(get_current_user)):
    """Get the timestamp and summary of the last successful sync."""
    logger.debug(f"GET /sync/last user={user_id[:8]}")
    last_sync = sync_service.get_last_sync(user_id)

    if not last_sync:
        logger.debug("GET /sync/last - No sync history found")
        return {"last_sync": None}

    logger.debug(f"GET /sync/last - Found: {last_sync.get('last_sync_at')}")
    return {"last_sync": last_sync}


# ============== PREFERENCES ROUTES ==============

@app.get("/preferences", response_model=UserPreferences)
def get_preferences(user_id: str = Depends(get_current_user)):
    """Return current user preferences."""
    prefs = _fetch_user_preferences(user_id)
    return UserPreferences(**prefs)


@app.post("/preferences", response_model=UserPreferences)
def save_preferences(body: UserPreferencesUpdate, user_id: str = Depends(get_current_user)):
    """Create or update user preferences (upserts the single row per user)."""
    logger.info(f"POST /preferences user={user_id[:8]}")
    try:
        existing = supabase_service.table("user_preferences").select("id").eq("user_id", user_id).limit(1).execute()
        updates = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        updates["user_id"] = user_id

        if existing.data:
            row_id = existing.data[0]["id"]
            r = supabase_service.table("user_preferences").update(updates).eq("id", row_id).execute()
        else:
            r = supabase_service.table("user_preferences").insert(updates).execute()

        return UserPreferences(**r.data[0])
    except Exception as e:
        logger.error(f"POST /preferences failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save preferences: {e}")


# ============== SCHEDULE ROUTES ==============

@app.post("/schedule/generate")
def generate_schedule_endpoint(user_id: str = Depends(get_current_user)):
    """Delete all planned blocks for the user, then generate a fresh 7-day AI schedule.

    Uses AI-powered scheduling (Groq) which reasons about priorities, task types,
    and the student's best focus hours. Falls back to rules-based if AI is unavailable.
    """
    from schedule_service import generate_schedule_ai

    try:
        # Remove existing planned blocks only (keep completed/skipped for history)
        supabase_service.table("time_blocks").delete().eq(
            "user_id", user_id
        ).eq("status", "planned").execute()

        result = generate_schedule_ai(user_id, supabase_service)

        if result["blocks"]:
            supabase_service.table("time_blocks").insert(result["blocks"]).execute()

        # Return saved blocks with assignment info joined
        from datetime import date as _date
        today = _date.today().isoformat()
        week_end = (_date.today() + timedelta(days=7)).isoformat()
        saved = supabase_service.table("time_blocks").select(
            "*, assignments(title, course_name, task_type, estimated_minutes)"
        ).eq("user_id", user_id).gte("date", today).lt("date", week_end).order("start_time").execute()

        return {
            "blocks": saved.data or [],
            "overbooked": result["overbooked"],
            "total_blocks": len(result["blocks"]),
        }
    except Exception as e:
        logger.error(f"POST /schedule/generate failed for user={user_id[:8]}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/schedule/week")
def get_week_schedule(
    week_start: Optional[str] = Query(default=None),
    user_id: str = Depends(get_current_user),
):
    """Return time blocks + assignment info for a given week (defaults to current Mon–Sun)."""
    from datetime import date as _date
    from zoneinfo import ZoneInfo
    mountain = ZoneInfo("America/Denver")

    if week_start:
        try:
            start = datetime.strptime(week_start, "%Y-%m-%d").date()
        except ValueError:
            start = datetime.now(mountain).date()
    else:
        start = datetime.now(mountain).date()

    # Snap to Monday
    start = start - timedelta(days=start.weekday())
    end = start + timedelta(days=7)

    blocks = supabase_service.table("time_blocks").select(
        "*, assignments(title, course_name, task_type, estimated_minutes)"
    ).eq("user_id", user_id).gte("date", start.isoformat()).lt(
        "date", end.isoformat()
    ).order("start_time").execute()

    return {
        "blocks": blocks.data or [],
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
    }


@app.post("/schedule/approve")
def approve_schedule(user_id: str = Depends(get_current_user)):
    """Mark all planned blocks as approved (plan_version 2)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    supabase_service.table("time_blocks").update({"plan_version": 2}).eq(
        "user_id", user_id
    ).eq("status", "planned").execute()
    return {"approved": True, "approved_at": now_iso}


@app.patch("/time-blocks/{block_id}")
def update_time_block(
    block_id: str,
    data: TimeBlockUpdate,
    user_id: str = Depends(get_current_user),
):
    """Update a time block's times or status (used for drag-drop and done/skip)."""
    update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = supabase_service.table("time_blocks").update(update_data).eq(
        "id", block_id
    ).eq("user_id", user_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Block not found")

    return {"block": result.data[0]}


@app.delete("/time-blocks/{block_id}", status_code=204)
def delete_time_block(block_id: str, user_id: str = Depends(get_current_user)):
    """Remove a time block without deleting the underlying task."""
    result = supabase_service.table("time_blocks").delete().eq(
        "id", block_id
    ).eq("user_id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Block not found")


# ============== AI ROUTES ==============

def _fetch_active_assignments(user_id: str) -> list[dict]:
    """Shared helper: fetch active assignments for AI context."""
    response = (
        supabase_service.table("assignments")
        .select("id, title, course_name, due_date, status, estimated_minutes, notes, description, assignment_type, task_type, point_value")
        .eq("user_id", user_id)
        .not_.in_("status", ["submitted", "unavailable"])
        .execute()
    )
    return response.data or []


def _fetch_user_preferences(user_id: str) -> dict:
    """Return the user_preferences row for this user, or sensible defaults if not set."""
    try:
        r = supabase_service.table("user_preferences").select("*").eq("user_id", user_id).limit(1).execute()
        if r.data:
            return r.data[0]
    except Exception as e:
        logger.warning(f"Could not fetch user preferences: {e}")
    return {
        "study_time": "evening",
        "session_length_minutes": 60,
        "advance_days": 2,
        "work_style": "spread_out",
        "involvement_level": "balanced",
    }


def _ai_error_to_http(e: Exception) -> HTTPException:
    """Translate ai_service exceptions into appropriate HTTP errors."""
    msg = str(e)
    if isinstance(e, RuntimeError):
        return HTTPException(status_code=503, detail=msg)
    if isinstance(e, ValueError):
        return HTTPException(status_code=502, detail=msg)
    if "rate_limit" in msg.lower() or "429" in msg:
        return HTTPException(
            status_code=429,
            detail="AI rate limit reached. Please wait a moment and try again.",
        )
    return HTTPException(status_code=502, detail=f"AI API error: {msg}")


@app.get("/ai/suggestions", response_model=AISuggestionsResponse)
def get_ai_suggestions(user_id: str = Depends(get_current_user)):
    """Return the latest cached AI suggestion per assignment."""
    try:
        # Join through assignments to filter by user_id
        assignment_ids_resp = (
            supabase_service.table("assignments")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )
        user_assignment_ids = {a["id"] for a in (assignment_ids_resp.data or [])}

        if not user_assignment_ids:
            return AISuggestionsResponse(
                suggestions=[],
                generated_at=datetime.now(timezone.utc).isoformat(),
            )

        response = (
            supabase_service.table("ai_suggestions")
            .select("*")
            .in_("assignment_id", list(user_assignment_ids))
            .order("generated_at", desc=True)
            .execute()
        )
        all_suggestions = response.data or []

        # Deduplicate: keep only the most recent row per assignment_id
        seen: set[str] = set()
        latest = []
        for s in all_suggestions:
            aid = s.get("assignment_id")
            if aid and aid not in seen:
                seen.add(aid)
                latest.append(s)

        logger.debug(f"GET /ai/suggestions user={user_id[:8]} - {len(latest)} suggestion(s)")
        return AISuggestionsResponse(
            suggestions=latest,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        logger.error(f"GET /ai/suggestions failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch suggestions: {e}")


@app.post("/ai/suggestions/generate", response_model=AISuggestionsResponse)
def generate_ai_suggestions(user_id: str = Depends(get_current_user)):
    """Generate fresh AI priority suggestions for all active assignments.

    Synchronous: waits for Groq (~3–8s). Saves results to ai_suggestions table.
    """
    logger.info(f"POST /ai/suggestions/generate user={user_id[:8]}")

    assignments = _fetch_active_assignments(user_id)
    if not assignments:
        return AISuggestionsResponse(
            suggestions=[],
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    prefs = _fetch_user_preferences(user_id)
    try:
        raw = ai_service.generate_suggestions(assignments, prefs)
    except Exception as e:
        raise _ai_error_to_http(e)

    # Validate and normalize
    now_iso = datetime.now(timezone.utc).isoformat()
    valid_ids = {a["id"] for a in assignments}
    rows = []
    for s in raw:
        aid = s.get("assignment_id", "")
        score = s.get("priority_score")
        if aid not in valid_ids:
            logger.warning(f"Skipping suggestion with unknown assignment_id: {aid}")
            continue
        if not isinstance(score, int) or not (1 <= score <= 10):
            logger.warning(f"Skipping suggestion with invalid score {score!r} for {aid}")
            continue
        rows.append({
            "assignment_id": aid,
            "priority_score": score,
            "suggested_start": s.get("suggested_start"),
            "rationale": (s.get("rationale") or "")[:200],
            "estimated_minutes": s.get("estimated_minutes"),
            "generated_at": now_iso,
        })

    if not rows:
        raise HTTPException(status_code=502, detail="AI returned no valid suggestions. Try again.")

    try:
        saved = supabase_service.table("ai_suggestions").insert(rows).execute()
        logger.info(f"POST /ai/suggestions/generate - saved {len(saved.data)} suggestion(s)")
    except Exception as e:
        logger.error(f"POST /ai/suggestions/generate - DB insert failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save suggestions: {e}")

    return AISuggestionsResponse(suggestions=saved.data, generated_at=now_iso)


@app.post("/ai/briefing/generate", response_model=AIBriefingResponse)
def generate_ai_briefing(user_id: str = Depends(get_current_user)):
    """Generate a natural-language daily plan briefing (~2s)."""
    logger.info(f"POST /ai/briefing/generate user={user_id[:8]}")

    assignments = _fetch_active_assignments(user_id)
    if not assignments:
        return AIBriefingResponse(
            briefing="No active assignments found. Enjoy the free time!",
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    prefs = _fetch_user_preferences(user_id)

    # Pull today's time blocks to make the briefing more specific
    from datetime import date as _date
    from zoneinfo import ZoneInfo
    _today_str = datetime.now(ZoneInfo("America/Denver")).date().isoformat()
    try:
        _tb = supabase_service.table("time_blocks").select(
            "*, assignments(title, course_name)"
        ).eq("user_id", user_id).eq("date", _today_str).order("start_time").execute()
        today_blocks = _tb.data or []
    except Exception:
        today_blocks = []

    try:
        briefing = ai_service.generate_briefing(assignments, prefs, today_blocks)
    except Exception as e:
        raise _ai_error_to_http(e)

    return AIBriefingResponse(
        briefing=briefing,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/ai/chat")
async def ai_chat(req: AIChatRequest, user_id: str = Depends(get_current_user)):
    """Streaming SSE chat endpoint. Returns text/event-stream.

    Each SSE event: data: {"delta": "..."}\n\n
    Final event:   data: [DONE]\n\n
    Error event:   data: {"error": "...", "code": N}\n\n
    """
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages list cannot be empty")

    assignments = _fetch_active_assignments(user_id)
    prefs = _fetch_user_preferences(user_id)
    messages_dicts = [{"role": m.role, "content": m.content} for m in req.messages]

    from zoneinfo import ZoneInfo
    _mt = ZoneInfo("America/Denver")
    _today = datetime.now(_mt).date().isoformat()
    _week_end = (datetime.now(_mt).date() + timedelta(days=7)).isoformat()

    # Fetch current week's time blocks so the AI knows what's already scheduled
    try:
        _blocks_resp = supabase_service.table("time_blocks").select(
            "*, assignments(title, course_name)"
        ).eq("user_id", user_id).gte("date", _today).lt("date", _week_end).order("start_time").execute()
        time_blocks = _blocks_resp.data or []
    except Exception:
        time_blocks = []

    # Fetch external calendar events so AI knows about outside commitments (with RRULE expansion)
    _ext_busy_lines = []
    try:
        from zoneinfo import ZoneInfo as _ZI
        import requests as _req_ext
        from icalendar import Calendar as _Cal_ext
        from datetime import timedelta as _td_ext, date as _date_ext
        import recurring_ical_events as _rie
        _mt_ext = _ZI("America/Denver")
        _today_dt = datetime.now(_mt_ext)
        _week_end_dt = _today_dt + timedelta(days=7)
        _ext_feeds = supabase_service.table("external_calendars").select("url, label").eq("user_id", user_id).execute()
        for _feed in (_ext_feeds.data or []):
            try:
                _resp = _req_ext.get(_feed["url"], timeout=8)
                _resp.raise_for_status()
                _cal = _Cal_ext.from_ical(_resp.content)
                for _comp in _rie.of(_cal).between(_today_dt, _week_end_dt):
                    _dtstart = _comp.get("DTSTART")
                    _summary = _comp.get("SUMMARY")
                    if not _dtstart or not _summary:
                        continue
                    _val = _dtstart.dt if hasattr(_dtstart, "dt") else _dtstart
                    _is_date = isinstance(_val, _date_ext) and not isinstance(_val, datetime)
                    if _is_date:
                        _sdt = datetime(_val.year, _val.month, _val.day, 0, 0, tzinfo=_mt_ext)
                    else:
                        _sdt = _val.astimezone(_mt_ext) if _val.tzinfo else _val.replace(tzinfo=_mt_ext)
                    _ext_busy_lines.append(
                        f"- {_sdt.strftime('%a %b %-d %-I:%M%p')}: {str(_summary).strip()} ({_feed['label']})"
                    )
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"POST /ai/chat: external calendar fetch failed: {e}")

    # Compute exact free time windows (same data used by auto-generate)
    try:
        from schedule_service import compute_free_slots, format_free_slots_for_ai
        free_slots_by_day = compute_free_slots(prefs, days=7)
        _base_slots_text = format_free_slots_for_ai(free_slots_by_day)
        if _ext_busy_lines:
            free_slots_text = _base_slots_text + "\n\nExternal calendar commitments this week:\n" + "\n".join(_ext_busy_lines)
        else:
            free_slots_text = _base_slots_text
    except Exception as e:
        logger.warning(f"POST /ai/chat: free slot computation failed: {e}")
        free_slots_text = ("\n\nExternal calendar commitments this week:\n" + "\n".join(_ext_busy_lines)) if _ext_busy_lines else None

    # Tally completed block minutes per assignment so AI knows remaining work
    try:
        _completed_resp = supabase_service.table("time_blocks").select(
            "assignment_id, start_time, end_time"
        ).eq("user_id", user_id).eq("status", "completed").execute()
        completed_minutes: dict = {}
        for cb in (_completed_resp.data or []):
            aid = cb.get("assignment_id")
            if not aid:
                continue
            try:
                s = datetime.fromisoformat(cb["start_time"].replace("Z", "+00:00"))
                e = datetime.fromisoformat(cb["end_time"].replace("Z", "+00:00"))
                completed_minutes[aid] = completed_minutes.get(aid, 0) + int((e - s).total_seconds() / 60)
            except Exception:
                pass
    except Exception:
        completed_minutes = {}

    logger.info(
        f"POST /ai/chat user={user_id[:8]} - {len(req.messages)} msg(s), "
        f"{len(time_blocks)} blocks, free_slots={'yes' if free_slots_text else 'no'}"
    )

    def event_stream():
        try:
            for chunk in ai_service.chat_stream(
                messages_dicts, assignments, prefs, time_blocks,
                free_slots_text=free_slots_text,
                completed_minutes=completed_minutes,
            ):
                yield f"data: {json.dumps({'delta': chunk})}\n\n"
        except RuntimeError as e:
            yield f"data: {json.dumps({'error': str(e), 'code': 503})}\n\n"
        except Exception as e:
            msg = str(e)
            code = 429 if ("rate_limit" in msg.lower() or "429" in msg) else 502
            yield f"data: {json.dumps({'error': msg, 'code': code})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/ai/apply-plan")
def ai_apply_plan(req: AIApplyPlanRequest, user_id: str = Depends(get_current_user)):
    """Extract a study plan from the conversation and write planned_start to assignments.

    Returns: {updated: N, assignments: [{id, planned_start}]}
    """
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages list cannot be empty")

    logger.info(f"POST /ai/apply-plan user={user_id[:8]} - {len(req.messages)} message(s)")

    assignments = _fetch_active_assignments(user_id)
    messages_dicts = [{"role": m.role, "content": m.content} for m in req.messages]

    # Fast path: parse the <plan> tag the AI already embedded — no extra LLM call needed
    import re as _re
    plan_items = None
    for msg in reversed(messages_dicts):
        if msg["role"] == "assistant":
            plan_match = _re.search(r'<plan>([\s\S]*?)</plan>', msg["content"])
            if plan_match:
                try:
                    plan_data = json.loads(plan_match.group(1).strip())
                    if isinstance(plan_data, dict) and "blocks" in plan_data:
                        plan_items = plan_data["blocks"]
                        logger.info(f"POST /ai/apply-plan: parsed <plan> tag directly ({len(plan_items)} blocks)")
                except Exception as e:
                    logger.warning(f"POST /ai/apply-plan: <plan> tag parse failed, falling back to extract: {e}")
            break

    # Fallback: run LLM extraction if no valid <plan> tag was found
    if plan_items is None:
        try:
            plan_items = ai_service.extract_plan(messages_dicts, assignments)
        except Exception as e:
            raise _ai_error_to_http(e)

    if not plan_items:
        raise HTTPException(
            status_code=422,
            detail="No study plan found in the conversation. Ask the AI to build a specific schedule first.",
        )

    valid_ids = {a["id"] for a in assignments}
    from zoneinfo import ZoneInfo
    from datetime import time as _time
    _MOUNTAIN = ZoneInfo("America/Denver")

    # Collect the assignment IDs the plan actually mentions before touching anything
    mentioned_ids = {
        item.get("assignment_id", "")
        for item in plan_items
        if item.get("assignment_id", "") in valid_ids
    }

    # Delete only planned blocks for assignments the plan mentions — surgical, not a full wipe.
    # Completed/skipped blocks are never touched.
    if mentioned_ids:
        supabase_service.table("time_blocks").delete().eq(
            "user_id", user_id
        ).eq("status", "planned").in_("assignment_id", list(mentioned_ids)).execute()

    new_blocks = []
    updated = []

    for item in plan_items:
        aid = item.get("assignment_id", "")
        if aid not in valid_ids:
            continue

        date_str = item.get("date") or item.get("planned_start", "")[:10]
        start_str = item.get("start_time", "")
        end_str = item.get("end_time", "")
        label = item.get("label", "")

        if not date_str:
            continue

        # Build real datetimes if we have times; otherwise use a day-only planned_start
        if start_str and end_str:
            try:
                from datetime import time as _time
                sh, sm = map(int, start_str.split(":"))
                eh, em = map(int, end_str.split(":"))
                from datetime import date as _d
                day = _d.fromisoformat(date_str)
                start_dt = datetime.combine(day, _time(sh, sm)).replace(tzinfo=_MOUNTAIN)
                end_dt   = datetime.combine(day, _time(eh, em)).replace(tzinfo=_MOUNTAIN)
                if end_dt > start_dt:
                    new_blocks.append({
                        "user_id":       user_id,
                        "assignment_id": aid,
                        "date":          date_str,
                        "start_time":    start_dt.isoformat(),
                        "end_time":      end_dt.isoformat(),
                        "label":         label,
                        "status":        "planned",
                        "plan_version":  1,
                    })
                    updated.append({"id": aid, "date": date_str, "start_time": start_str, "end_time": end_str})
                    # Update planned_start + planned_end on the assignment for timeline / ICS export
                    supabase_service.table("assignments").update({
                        "planned_start": start_dt.isoformat(),
                        "planned_end":   end_dt.isoformat(),
                    }).eq("id", aid).eq("user_id", user_id).execute()
                    continue
            except Exception as e:
                logger.warning(f"POST /ai/apply-plan - could not parse times for {aid}: {e}")

        # Fallback: date-only — just update planned_start
        try:
            supabase_service.table("assignments").update(
                {"planned_start": date_str + "T00:00:00+00:00"}
            ).eq("id", aid).eq("user_id", user_id).execute()
            updated.append({"id": aid, "date": date_str})
        except Exception as e:
            logger.warning(f"POST /ai/apply-plan - failed to update {aid}: {e}")

    if new_blocks:
        try:
            supabase_service.table("time_blocks").insert(new_blocks).execute()
        except Exception as e:
            logger.error(f"POST /ai/apply-plan - time_blocks insert failed: {e}")

    logger.info(f"POST /ai/apply-plan user={user_id[:8]} - {len(new_blocks)} blocks, {len(updated)} updated")
    return {"updated": len(updated), "blocks": len(new_blocks), "assignments": updated}


class AIContextUpdate(BaseModel):
    context: str  # New/updated student_context string (full replacement)


@app.post("/ai/update-context")
def update_student_context(req: AIContextUpdate, user_id: str = Depends(get_current_user)):
    """Persist a student context string to user_preferences.student_context.

    Called when the AI (or user) surfaces important facts about the student's
    courses or schedule that should inform future AI calls.
    """
    context = (req.context or "").strip()[:2000]  # Cap at 2000 chars
    logger.info(f"POST /ai/update-context user={user_id[:8]} - {len(context)} chars")

    existing = supabase_service.table("user_preferences").select("id").eq(
        "user_id", user_id
    ).limit(1).execute()

    if existing.data:
        supabase_service.table("user_preferences").update(
            {"student_context": context}
        ).eq("user_id", user_id).execute()
    else:
        supabase_service.table("user_preferences").insert(
            {"user_id": user_id, "student_context": context}
        ).execute()

    return {"updated": True, "length": len(context)}


# ============== LS CLASSIFICATION HELPERS ==============

def _classify_and_save(new_items: list[dict], course_name: str) -> None:
    """AI-classify a batch of new LS items and write content_type back to DB."""
    try:
        mapping = ai_service.classify_ls_events(
            [{"uid": it["uid"], "title": it["title"]} for it in new_items],
            course_name,
        )
        for it in new_items:
            ct = mapping.get(it["uid"], "graded")
            supabase_service.table("assignments").update(
                {"content_type": ct}
            ).eq("id", it["id"]).execute()
        logger.info(f"_classify_and_save: classified {len(new_items)} items for {course_name!r}")
    except Exception as e:
        logger.error(f"_classify_and_save failed: {e}")


def _count_pending_review(user_id: str, feed_id: str) -> int:
    """Count assignments for this feed awaiting user review (classification_confirmed=false)."""
    try:
        feed_resp = supabase_service.table("ls_ical_feeds").select("url, course_name").eq(
            "id", feed_id
        ).limit(1).execute()
        if not feed_resp.data:
            return 0
        course_name = feed_resp.data[0]["course_name"]
        resp = supabase_service.table("assignments").select("id", count="exact").eq(
            "user_id", user_id
        ).eq("course_name", course_name).eq("classification_confirmed", False).execute()
        return resp.count or 0
    except Exception:
        return 0


# ============== LEARNING SUITE iCAL ROUTES ==============

@app.get("/ls-feeds")
def get_ls_feeds(user_id: str = Depends(get_current_user)):
    """Return all saved iCal feed URLs for the user."""
    result = supabase_service.table("ls_ical_feeds").select("*").eq(
        "user_id", user_id
    ).order("created_at").execute()
    return {"feeds": result.data or []}


@app.post("/ls-feeds", status_code=201)
def add_ls_feed(body: LSICalFeedCreate, user_id: str = Depends(get_current_user)):
    """Save a new iCal feed URL."""
    url = body.url.strip()
    course_name = body.course_name.strip()
    if not url or not course_name:
        raise HTTPException(status_code=400, detail="url and course_name are required")
    _validate_ical_url(url)
    result = supabase_service.table("ls_ical_feeds").insert({
        "user_id": user_id,
        "url": url,
        "course_name": course_name,
    }).execute()
    return {"feed": result.data[0]}


@app.post("/ls-feeds/preview")
def preview_ls_feed(body: LSICalFeedCreate):
    """Fetch and parse an iCal URL without saving or writing to DB. Returns first 5 events."""
    _validate_ical_url(body.url.strip())
    from ical_client import fetch_and_parse
    try:
        assignments = fetch_and_parse(body.url.strip(), body.course_name.strip())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch iCal feed: {e}")
    preview = [
        {"title": a["title"], "due_date": a["due_date"], "assignment_type": a["assignment_type"]}
        for a in assignments[:5]
    ]
    return {"total": len(assignments), "preview": preview}


@app.post("/ls-feeds/sync")
def sync_ls_feeds(user_id: str = Depends(get_current_user)):
    """Sync all saved iCal feeds for the user. Returns per-feed results."""
    from ical_client import fetch_and_parse, update_database
    now_iso = datetime.now(timezone.utc).isoformat()

    feeds_resp = supabase_service.table("ls_ical_feeds").select("*").eq(
        "user_id", user_id
    ).execute()
    feeds = feeds_resp.data or []

    if not feeds:
        return {"synced": 0, "results": []}

    results = []
    for feed in feeds:
        try:
            assignments = fetch_and_parse(feed["url"], feed["course_name"])
            counts = update_database(assignments, supabase_client=supabase_service, user_id=user_id, feed_url=feed["url"])
            supabase_service.table("ls_ical_feeds").update(
                {"last_synced_at": now_iso}
            ).eq("id", feed["id"]).execute()

            # AI-classify any newly inserted items
            new_items = counts.pop("new_items", [])
            if new_items:
                _classify_and_save(new_items, feed["course_name"])

            pending = _count_pending_review(user_id, feed["id"])
            results.append({
                "feed_id": feed["id"],
                "course_name": feed["course_name"],
                **counts,
                "pending_review": pending,
                "error": None,
            })
        except Exception as e:
            logger.error(f"POST /ls-feeds/sync - feed {feed['id']} failed: {e}")
            results.append({"feed_id": feed["id"], "course_name": feed["course_name"], "error": str(e)})

    return {"synced": len(feeds), "results": results}


@app.get("/ls-feeds/{feed_id}/pending-review")
def get_pending_review(feed_id: str, user_id: str = Depends(get_current_user)):
    """Return items for this feed that have been AI-classified but not yet confirmed by the user."""
    feed_resp = supabase_service.table("ls_ical_feeds").select("course_name").eq(
        "id", feed_id
    ).eq("user_id", user_id).limit(1).execute()
    if not feed_resp.data:
        raise HTTPException(status_code=404, detail="Feed not found")
    course_name = feed_resp.data[0]["course_name"]

    resp = supabase_service.table("assignments").select(
        "id, title, content_type, due_date, assignment_type"
    ).eq("user_id", user_id).eq("course_name", course_name).eq(
        "classification_confirmed", False
    ).order("due_date").execute()

    return {"items": resp.data or [], "course_name": course_name}


class ClassificationConfirm(BaseModel):
    items: list[dict]  # [{id: str, content_type: "graded"|"course_content"}, ...]


@app.post("/ls-feeds/{feed_id}/confirm-classifications")
def confirm_classifications(
    feed_id: str,
    body: ClassificationConfirm,
    user_id: str = Depends(get_current_user),
):
    """Save user-confirmed content_type for each item and mark classification_confirmed=true."""
    if not body.items:
        return {"confirmed": 0}

    # Verify feed belongs to user
    feed_resp = supabase_service.table("ls_ical_feeds").select("id").eq(
        "id", feed_id
    ).eq("user_id", user_id).limit(1).execute()
    if not feed_resp.data:
        raise HTTPException(status_code=404, detail="Feed not found")

    confirmed = 0
    for item in body.items:
        aid = item.get("id")
        ct = item.get("content_type", "graded")
        if not aid or ct not in ("graded", "course_content"):
            continue
        supabase_service.table("assignments").update({
            "content_type": ct,
            "classification_confirmed": True,
        }).eq("id", aid).eq("user_id", user_id).execute()
        confirmed += 1

    logger.info(f"POST /ls-feeds/{feed_id}/confirm-classifications user={user_id[:8]} - {confirmed} confirmed")
    return {"confirmed": confirmed}


@app.patch("/ls-feeds/{feed_id}")
def update_ls_feed(feed_id: str, body: LSICalFeedUpdate, user_id: str = Depends(get_current_user)):
    """Update url and/or course_name of a saved iCal feed."""
    updates = {}
    if body.url is not None:
        url = body.url.strip()
        if not url:
            raise HTTPException(status_code=400, detail="url cannot be empty")
        _validate_ical_url(url)
        updates["url"] = url
    if body.course_name is not None:
        course_name = body.course_name.strip()
        if not course_name:
            raise HTTPException(status_code=400, detail="course_name cannot be empty")
        updates["course_name"] = course_name
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = supabase_service.table("ls_ical_feeds").update(updates).eq(
        "id", feed_id
    ).eq("user_id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Feed not found")
    return {"feed": result.data[0]}


@app.delete("/ls-feeds/{feed_id}", status_code=204)
def delete_ls_feed(feed_id: str, user_id: str = Depends(get_current_user)):
    """Delete a saved iCal feed by ID."""
    result = supabase_service.table("ls_ical_feeds").delete().eq(
        "id", feed_id
    ).eq("user_id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Feed not found")


@app.get("/ls-feeds/class-events")
def get_ls_class_events(
    week_start: str = Query(None),
    user_id: str = Depends(get_current_user),
):
    """Return class session events from all LS iCal feeds for the given week.

    These are the actual class meeting times embedded in LS iCal feeds —
    filtered *out* during assignment import but useful for the calendar grid.
    """
    from zoneinfo import ZoneInfo as _ZI
    from datetime import timedelta as _td

    _mt = _ZI("America/Denver")
    if week_start:
        try:
            _ws = datetime.strptime(week_start, "%Y-%m-%d").replace(tzinfo=_mt)
        except ValueError:
            _ws = datetime.now(_mt)
    else:
        _ws = datetime.now(_mt)
    _ws = _ws.replace(hour=0, minute=0, second=0, microsecond=0)
    _we = _ws + _td(days=7)
    _ws_str = _ws.date().isoformat()
    _we_str = _we.date().isoformat()

    feeds = supabase_service.table("ls_ical_feeds").select("url, course_name").eq("user_id", user_id).execute()
    events = []
    for feed in (feeds.data or []):
        try:
            from ical_client import fetch_class_sessions
            sessions = fetch_class_sessions(feed["url"], feed["course_name"])
            for s in sessions:
                if _ws_str <= s["date"] < _we_str:
                    events.append(s)
        except Exception as e:
            logger.warning(f"GET /ls-feeds/class-events feed={feed.get('course_name')}: {e}")

    return {"events": events}


# ============== EXTERNAL CALENDAR ROUTES ==============

@app.get("/external-calendars")
def list_external_calendars(user_id: str = Depends(get_current_user)):
    """List all saved external calendar feeds for the current user."""
    result = supabase_service.table("external_calendars").select("*").eq("user_id", user_id).execute()
    return {"calendars": result.data or []}


@app.post("/external-calendars", status_code=201)
def add_external_calendar(body: ExternalCalendarCreate, user_id: str = Depends(get_current_user)):
    """Save a new external iCal URL (e.g. Google Calendar secret address)."""
    _validate_ical_url(body.url.strip())
    row = {"url": body.url.strip(), "label": body.label.strip() or "My Calendar", "user_id": user_id}
    result = supabase_service.table("external_calendars").insert(row).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to save calendar")
    return {"calendar": result.data[0]}


@app.delete("/external-calendars/{cal_id}", status_code=204)
def delete_external_calendar(cal_id: str, user_id: str = Depends(get_current_user)):
    """Delete an external calendar feed."""
    supabase_service.table("external_calendars").delete().eq("id", cal_id).eq("user_id", user_id).execute()


@app.get("/external-calendars/events")
def get_external_calendar_events(
    week_start: str = Query(None),
    user_id: str = Depends(get_current_user),
):
    """Fetch and return events from all saved external calendars for a given week.

    Returns events as [{title, start, end, label, all_day}] in Mountain Time.
    Uses recurring-ical-events to expand RRULE recurring events (e.g. Google Calendar).
    If week_start is not provided, defaults to current week.
    """
    from datetime import date as _date_type, timedelta as td
    from zoneinfo import ZoneInfo
    import requests as _requests
    from icalendar import Calendar as _Calendar
    import recurring_ical_events

    MOUNTAIN = ZoneInfo("America/Denver")

    # Parse week range
    if week_start:
        try:
            ws = datetime.strptime(week_start, "%Y-%m-%d").replace(tzinfo=MOUNTAIN)
        except ValueError:
            ws = datetime.now(MOUNTAIN)
    else:
        ws = datetime.now(MOUNTAIN)
        ws = ws - td(days=(ws.weekday()))  # Monday
    ws = ws.replace(hour=0, minute=0, second=0, microsecond=0)
    we = ws + td(days=7)

    # Load all feeds
    feeds_result = supabase_service.table("external_calendars").select("*").eq("user_id", user_id).execute()
    feeds = feeds_result.data or []

    events = []
    for feed in feeds:
        url = feed.get("url", "")
        label = feed.get("label", "External")
        try:
            resp = _requests.get(url, timeout=10)
            resp.raise_for_status()
            cal = _Calendar.from_ical(resp.content)

            # Use recurring_ical_events to expand all RRULE/recurring events for the week
            expanded = recurring_ical_events.of(cal).between(ws, we)

            for component in expanded:
                dtstart_prop = component.get("DTSTART")
                dtend_prop = component.get("DTEND")
                summary = component.get("SUMMARY")
                if not dtstart_prop or not summary:
                    continue

                dtstart_val = dtstart_prop.dt if hasattr(dtstart_prop, "dt") else dtstart_prop
                dtend_val = dtend_prop.dt if (dtend_prop and hasattr(dtend_prop, "dt")) else None

                all_day = isinstance(dtstart_val, _date_type) and not isinstance(dtstart_val, datetime)

                if all_day:
                    start_dt = datetime(dtstart_val.year, dtstart_val.month, dtstart_val.day,
                                        0, 0, 0, tzinfo=MOUNTAIN)
                    if dtend_val and isinstance(dtend_val, _date_type):
                        end_dt = datetime(dtend_val.year, dtend_val.month, dtend_val.day,
                                          23, 59, 59, tzinfo=MOUNTAIN)
                    else:
                        end_dt = start_dt.replace(hour=23, minute=59, second=59)
                else:
                    if dtstart_val.tzinfo is None:
                        dtstart_val = dtstart_val.replace(tzinfo=MOUNTAIN)
                    start_dt = dtstart_val.astimezone(MOUNTAIN)
                    if dtend_val:
                        if dtend_val.tzinfo is None:
                            dtend_val = dtend_val.replace(tzinfo=MOUNTAIN)
                        end_dt = dtend_val.astimezone(MOUNTAIN)
                    else:
                        end_dt = start_dt + td(hours=1)

                events.append({
                    "title": str(summary).strip(),
                    "start": start_dt.isoformat(),
                    "end": end_dt.isoformat(),
                    "calendar_label": label,
                    "calendar_id": feed["id"],
                    "all_day": all_day,
                })
        except Exception as e:
            logger.warning(f"External calendar fetch failed for {url[:60]}: {e}")
            continue

    return {"events": events}


# ============== PUSH NOTIFICATION ROUTES ==============

@app.get("/push/vapid-public-key")
def get_vapid_public_key():
    """Return the VAPID public key for the frontend to use when subscribing."""
    key = os.getenv("VAPID_PUBLIC_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="Push notifications not configured.")
    return {"publicKey": key}


@app.post("/push/subscribe")
def push_subscribe(sub: PushSubscription, user_id: str = Depends(get_current_user)):
    """Save a browser push subscription (upsert by endpoint)."""
    logger.info(f"POST /push/subscribe user={user_id[:8]} - {sub.endpoint[:60]}…")
    try:
        existing = supabase_service.table("push_subscriptions").select("id").eq("endpoint", sub.endpoint).eq("user_id", user_id).execute()
        row = {
            "endpoint": sub.endpoint,
            "p256dh": sub.keys.get("p256dh", ""),
            "auth": sub.keys.get("auth", ""),
            "user_id": user_id,
        }
        if existing.data:
            supabase_service.table("push_subscriptions").update(row).eq("endpoint", sub.endpoint).eq("user_id", user_id).execute()
        else:
            supabase_service.table("push_subscriptions").insert(row).execute()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"POST /push/subscribe failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/push/subscribe")
def push_unsubscribe(sub: PushSubscription, user_id: str = Depends(get_current_user)):
    """Remove a push subscription."""
    try:
        supabase_service.table("push_subscriptions").delete().eq("endpoint", sub.endpoint).eq("user_id", user_id).execute()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/push/send-deadline-reminders")
def send_deadline_reminders(user_id: str = Depends(get_current_user)):
    """Send push notifications for assignments due within 24 hours.

    Called on demand or by an external cron. Only sends if subscriptions exist.
    """
    logger.info(f"POST /push/send-deadline-reminders user={user_id[:8]}")

    vapid_private = os.getenv("VAPID_PRIVATE_KEY", "").replace("\\n", "\n")
    vapid_public = os.getenv("VAPID_PUBLIC_KEY", "")
    vapid_contact = os.getenv("VAPID_CONTACT", "mailto:admin@campusai.app")

    if not vapid_private or not vapid_public:
        raise HTTPException(status_code=503, detail="VAPID keys not configured.")

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        raise HTTPException(status_code=503, detail="pywebpush not installed.")

    # Fetch subscriptions for this user only
    subs_res = supabase_service.table("push_subscriptions").select("*").eq("user_id", user_id).execute()
    subscriptions = subs_res.data or []
    if not subscriptions:
        return {"sent": 0, "message": "No subscribers."}

    # Find assignments due in the next 24 hours for this user
    now = datetime.now(timezone.utc)
    in_24h = (now + timedelta(hours=24)).isoformat()
    due_soon = (
        supabase_service.table("assignments")
        .select("title, course_name, due_date")
        .eq("user_id", user_id)
        .not_.in_("status", ["submitted", "unavailable"])
        .lte("due_date", in_24h)
        .gte("due_date", now.isoformat())
        .order("due_date")
        .execute()
    ).data or []

    if not due_soon:
        return {"sent": 0, "message": "No assignments due soon."}

    # Build notification payload
    titles = [f"{a['title']} ({a['course_name']})" for a in due_soon[:3]]
    body = "Due soon: " + "; ".join(titles)
    if len(due_soon) > 3:
        body += f" +{len(due_soon) - 3} more"

    import json as _json
    payload = _json.dumps({
        "title": "CampusAI Reminder",
        "body": body,
        "icon": "/favicon.ico",
        "badge": "/favicon.ico",
    })

    sent = 0
    stale = []
    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=payload,
                vapid_private_key=vapid_private,
                vapid_claims={"sub": vapid_contact},
            )
            sent += 1
        except WebPushException as e:
            if e.response and e.response.status_code in (404, 410):
                stale.append(sub["endpoint"])
            else:
                logger.warning(f"Push failed for {sub['endpoint'][:40]}: {e}")

    # Clean up stale subscriptions
    for endpoint in stale:
        supabase_service.table("push_subscriptions").delete().eq("endpoint", endpoint).eq("user_id", user_id).execute()

    logger.info(f"POST /push/send-deadline-reminders user={user_id[:8]} — sent {sent}, removed {len(stale)} stale")
    return {"sent": sent, "removed_stale": len(stale)}


@app.on_event("startup")
def startup_event():
    """Log registered routes on startup for debugging."""
    logger.info("=" * 50)
    logger.info("REGISTERED ROUTES:")
    for route in app.routes:
        if hasattr(route, 'methods') and hasattr(route, 'path'):
            logger.info(f"  {list(route.methods)} {route.path}")
    logger.info("=" * 50)
    logger.info("API docs available at: http://localhost:8000/docs")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
