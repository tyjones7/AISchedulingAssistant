import os
import json
import logging
from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from supabase import create_client

from sync_service import sync_service
import canvas_auth_store
import ai_service

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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


class UserPreferencesUpdate(BaseModel):
    study_time: Optional[Literal["morning", "afternoon", "evening", "night"]] = None
    session_length_minutes: Optional[int] = None
    advance_days: Optional[int] = None
    work_style: Optional[Literal["spread_out", "batch"]] = None
    involvement_level: Optional[Literal["proactive", "balanced", "prompt_only"]] = None
    weekly_schedule: Optional[list] = None
    work_start: Optional[str] = None
    work_end: Optional[str] = None


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
    user_id: str = Depends(get_current_user),
):
    """Get assignments. Pass exclude_past_submitted=true to skip submitted past-due items."""
    query = supabase_service.table("assignments").select("*").eq("user_id", user_id).order("due_date")
    if exclude_past_submitted:
        now_iso = datetime.now(timezone.utc).isoformat()
        # Return assignments where status is not submitted, OR due_date is in the future
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
    """Delete all planned blocks for the user, then generate a fresh 7-day schedule."""
    from schedule_service import generate_schedule

    # Remove existing planned blocks only (keep completed/skipped for history)
    supabase_service.table("time_blocks").delete().eq(
        "user_id", user_id
    ).eq("status", "planned").execute()

    result = generate_schedule(user_id, supabase_service)

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
        .select("id, title, course_name, due_date, status, estimated_minutes, notes, description, assignment_type, point_value")
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
    try:
        briefing = ai_service.generate_briefing(assignments, prefs)
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

    logger.info(f"POST /ai/chat user={user_id[:8]} - {len(req.messages)} message(s)")

    def event_stream():
        try:
            for chunk in ai_service.chat_stream(messages_dicts, assignments, prefs):
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
    updated = []
    for item in plan_items:
        aid = item.get("assignment_id", "")
        planned_start = item.get("planned_start")
        if aid not in valid_ids or not planned_start:
            continue
        try:
            supabase_service.table("assignments").update(
                {"planned_start": planned_start}
            ).eq("id", aid).eq("user_id", user_id).execute()
            updated.append({"id": aid, "planned_start": planned_start})
        except Exception as e:
            logger.warning(f"POST /ai/apply-plan - failed to update {aid}: {e}")

    logger.info(f"POST /ai/apply-plan user={user_id[:8]} - updated {len(updated)} assignment(s)")
    return {"updated": len(updated), "assignments": updated}


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
