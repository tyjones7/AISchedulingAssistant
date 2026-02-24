import os
import json
import logging
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from supabase import create_client

from sync_service import sync_service
import auth_store
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


class AuthStatusResponse(BaseModel):
    authenticated: bool
    netid: Optional[str] = None
    canvas_connected: bool = False


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


class UserPreferencesUpdate(BaseModel):
    study_time: Optional[Literal["morning", "afternoon", "evening", "night"]] = None
    session_length_minutes: Optional[int] = None
    advance_days: Optional[int] = None
    work_style: Optional[Literal["spread_out", "batch"]] = None
    involvement_level: Optional[Literal["proactive", "balanced", "prompt_only"]] = None


load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "Missing required environment variables: "
        + ("SUPABASE_URL " if not SUPABASE_URL else "")
        + ("SUPABASE_KEY" if not SUPABASE_KEY else "")
        + ". Check your .env file or environment."
    )

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

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


@app.get("/")
def read_root():
    return {"message": "Hello World"}


@app.get("/ping")
def ping():
    return {"status": "ok", "message": "Backend is connected!"}


# ============== AUTH ROUTES ==============
# Handle browser-based BYU authentication

@app.post("/auth/browser-login")
def browser_login():
    """Start browser-based BYU login.

    Opens a browser window to BYU's login page where the user
    authenticates directly. We never see their password.
    """
    import threading
    from scraper.learning_suite_scraper import LearningSuiteScraper

    # Check if already authenticating
    if auth_store.is_authenticated():
        return {"success": True, "message": "Already authenticated", "task_id": None}

    task_id = auth_store.create_browser_auth_task()
    logger.info(f"POST /auth/browser-login - Starting browser auth task: {task_id}")

    def run_browser_auth():
        try:
            auth_store.update_browser_auth_status(task_id, auth_store.BrowserAuthStatus.OPENING)

            # Open visible browser for user to log in
            scraper = LearningSuiteScraper(headless=False)
            scraper._setup_driver()

            auth_store.update_browser_auth_status(task_id, auth_store.BrowserAuthStatus.WAITING_FOR_LOGIN)

            # Navigate to Learning Suite - will redirect to CAS login
            scraper.driver.get("https://learningsuite.byu.edu")

            # Wait for user to complete login (check every 2 seconds for up to 5 minutes)
            import time
            max_wait = 300  # 5 minutes
            waited = 0
            check_interval = 2

            while waited < max_wait:
                current_url = scraper.driver.current_url

                # Check if on Duo MFA page
                if "duo" in current_url.lower() or "authenticate" in current_url.lower():
                    auth_store.update_browser_auth_status(task_id, auth_store.BrowserAuthStatus.WAITING_FOR_MFA)

                # Check if successfully logged in (URL has session pattern)
                import re
                if re.match(r'https://learningsuite\.byu\.edu/\.[A-Za-z0-9]+', current_url):
                    logger.info(f"Browser auth [{task_id[:8]}] - Login successful!")
                    dynamic_base_url = scraper._extract_dynamic_base_url()
                    cookies = scraper.driver.get_cookies()
                    logger.info(f"Browser auth [{task_id[:8]}] - Extracted {len(cookies)} cookies")

                    # Log cookie details for debugging session issues
                    for c in cookies:
                        logger.debug(f"Browser auth [{task_id[:8]}] - Cookie: {c.get('name')} domain={c.get('domain')} secure={c.get('secure')} httpOnly={c.get('httpOnly')} sameSite={c.get('sameSite')}")

                    # Extract localStorage and sessionStorage for session persistence
                    local_storage = {}
                    session_storage = {}
                    try:
                        local_storage = scraper.driver.execute_script(
                            "var items = {}; "
                            "for (var i = 0; i < localStorage.length; i++) { "
                            "  var key = localStorage.key(i); "
                            "  items[key] = localStorage.getItem(key); "
                            "} "
                            "return items;"
                        ) or {}
                        logger.info(f"Browser auth [{task_id[:8]}] - Extracted {len(local_storage)} localStorage items")
                    except Exception as e:
                        logger.debug(f"Browser auth [{task_id[:8]}] - Could not extract localStorage: {e}")

                    try:
                        session_storage = scraper.driver.execute_script(
                            "var items = {}; "
                            "for (var i = 0; i < sessionStorage.length; i++) { "
                            "  var key = sessionStorage.key(i); "
                            "  items[key] = sessionStorage.getItem(key); "
                            "} "
                            "return items;"
                        ) or {}
                        logger.info(f"Browser auth [{task_id[:8]}] - Extracted {len(session_storage)} sessionStorage items")
                    except Exception as e:
                        logger.debug(f"Browser auth [{task_id[:8]}] - Could not extract sessionStorage: {e}")

                    # Store cookies + URL + web storage, then close the visible browser
                    auth_store.set_session_data(cookies, dynamic_base_url)
                    auth_store.set_web_storage(local_storage, session_storage)
                    scraper.close()
                    logger.info(f"Browser auth [{task_id[:8]}] - Visible browser closed")

                    auth_store.update_browser_auth_status(task_id, auth_store.BrowserAuthStatus.AUTHENTICATED)
                    return

                time.sleep(check_interval)
                waited += check_interval

            # Timeout
            scraper.close()
            auth_store.update_browser_auth_status(
                task_id,
                auth_store.BrowserAuthStatus.FAILED,
                "Login timed out. Please try again."
            )

        except Exception as e:
            logger.error(f"Browser auth [{task_id[:8]}] failed: {e}")
            auth_store.update_browser_auth_status(
                task_id,
                auth_store.BrowserAuthStatus.FAILED,
                str(e)
            )

    # Run in background thread
    thread = threading.Thread(target=run_browser_auth, daemon=True)
    thread.start()

    return {"success": True, "task_id": task_id, "message": "Browser opening..."}


@app.get("/auth/browser-status/{task_id}")
def browser_auth_status(task_id: str):
    """Check the status of a browser authentication task."""
    task = auth_store.get_browser_auth_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Auth task not found")

    return {
        "task_id": task.task_id,
        "status": task.status.value,
        "error": task.error,
    }


@app.get("/auth/status", response_model=AuthStatusResponse)
def auth_status():
    """Check if user is authenticated (LS and/or Canvas)."""
    is_auth = auth_store.is_authenticated()
    return AuthStatusResponse(
        authenticated=is_auth,
        netid=None,  # We don't store netid with browser auth
        canvas_connected=canvas_auth_store.is_connected(),
    )


@app.post("/auth/logout")
def logout():
    """Clear authentication and close browser session."""
    logger.info("POST /auth/logout - Clearing authentication")
    auth_store.clear_authentication()
    canvas_auth_store.clear_token()
    return {"success": True, "message": "Logged out"}


# ============== CANVAS AUTH ROUTES ==============

@app.post("/auth/canvas-token")
def set_canvas_token(req: CanvasTokenRequest):
    """Validate and store a Canvas API token."""
    token = req.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token is required")

    valid, result = canvas_auth_store.validate_token(token)
    if not valid:
        raise HTTPException(status_code=401, detail=result)

    canvas_auth_store.set_token(token, result)
    logger.info(f"POST /auth/canvas-token - Connected as {result}")
    return {"success": True, "user_name": result}


@app.get("/auth/canvas-status")
def canvas_status():
    """Check if Canvas is connected."""
    return {
        "connected": canvas_auth_store.is_connected(),
        "user_name": canvas_auth_store.get_user_name(),
    }


@app.delete("/auth/canvas-token")
def delete_canvas_token():
    """Disconnect Canvas."""
    canvas_auth_store.clear_token()
    logger.info("DELETE /auth/canvas-token - Disconnected")
    return {"success": True}


@app.get("/assignments")
def get_assignments(exclude_past_submitted: bool = Query(default=False)):
    """Get assignments. Pass exclude_past_submitted=true to skip submitted past-due items."""
    query = supabase.table("assignments").select("*").order("due_date")
    if exclude_past_submitted:
        now_iso = datetime.now(timezone.utc).isoformat()
        # Return assignments where status is not submitted, OR due_date is in the future
        query = query.or_(f"status.neq.submitted,due_date.gte.{now_iso}")
    response = query.execute()
    return {"assignments": response.data}


# IMPORTANT: Static routes must come BEFORE parameterized routes
@app.get("/assignments/stats/summary")
def get_assignment_stats():
    """Get assignment statistics for the dashboard."""
    from zoneinfo import ZoneInfo

    response = supabase.table("assignments").select("*").execute()
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


@app.get("/assignments/{assignment_id}")
def get_assignment(assignment_id: str):
    """Get a single assignment by ID."""
    response = supabase.table("assignments").select("*").eq("id", assignment_id).execute()

    if not response.data:
        raise HTTPException(status_code=404, detail="Assignment not found")

    return {"assignment": response.data[0]}


@app.patch("/assignments/{assignment_id}")
def update_assignment(assignment_id: str, update: AssignmentUpdate):
    """Update assignment fields including status and planning data."""
    # Build update dict with only provided fields
    update_data = {}

    if update.status is not None:
        update_data["status"] = update.status
    if update.estimated_minutes is not None:
        update_data["estimated_minutes"] = update.estimated_minutes
    if update.planned_start is not None:
        update_data["planned_start"] = update.planned_start
    if update.planned_end is not None:
        update_data["planned_end"] = update.planned_end
    if update.notes is not None:
        update_data["notes"] = update.notes

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

    response = supabase.table("assignments").update(
        update_data
    ).eq("id", assignment_id).execute()

    if not response.data:
        raise HTTPException(status_code=404, detail="Assignment not found")

    return {"assignment": response.data[0]}


# ============== SYNC ROUTES ==============
# These handle Learning Suite synchronization

@app.post("/sync/start", response_model=SyncStartResponse)
def start_sync():
    """Start a new Learning Suite sync.

    Returns immediately with a task_id that can be polled for status.
    """
    logger.info("POST /sync/start - Starting new sync")
    task_id, error = sync_service.start_sync()

    if error:
        logger.warning(f"POST /sync/start - Rejected: {error}")
        raise HTTPException(status_code=409, detail=error)

    logger.info(f"POST /sync/start - Created task: {task_id}")
    return SyncStartResponse(task_id=task_id, message="Sync started")


@app.get("/sync/status/{task_id}", response_model=SyncStatusResponse)
def get_sync_status(task_id: str):
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
def get_last_sync():
    """Get the timestamp and summary of the last successful sync."""
    logger.debug("GET /sync/last")
    last_sync = sync_service.get_last_sync()

    if not last_sync:
        logger.debug("GET /sync/last - No sync history found")
        return {"last_sync": None}

    logger.debug(f"GET /sync/last - Found: {last_sync.get('last_sync_at')}")
    return {"last_sync": last_sync}


# ============== PREFERENCES ROUTES ==============

@app.get("/preferences", response_model=UserPreferences)
def get_preferences():
    """Return current user preferences."""
    prefs = _fetch_user_preferences()
    return UserPreferences(**prefs)


@app.post("/preferences", response_model=UserPreferences)
def save_preferences(body: UserPreferencesUpdate):
    """Create or update user preferences (upserts the single row)."""
    logger.info("POST /preferences")
    try:
        existing = supabase.table("user_preferences").select("id").limit(1).execute()
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()

        if existing.data:
            row_id = existing.data[0]["id"]
            r = supabase.table("user_preferences").update(updates).eq("id", row_id).execute()
        else:
            r = supabase.table("user_preferences").insert(updates).execute()

        return UserPreferences(**r.data[0])
    except Exception as e:
        logger.error(f"POST /preferences failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save preferences: {e}")


# ============== AI ROUTES ==============

def _fetch_active_assignments() -> list[dict]:
    """Shared helper: fetch active assignments for AI context."""
    response = (
        supabase.table("assignments")
        .select("id, title, course_name, due_date, status, estimated_minutes, notes, description, assignment_type, point_value")
        .not_.in_("status", ["submitted", "unavailable"])
        .execute()
    )
    return response.data or []


def _fetch_user_preferences() -> dict:
    """Return the single user_preferences row, or sensible defaults if not set."""
    try:
        r = supabase.table("user_preferences").select("*").limit(1).execute()
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
def get_ai_suggestions():
    """Return the latest cached AI suggestion per assignment."""
    try:
        response = (
            supabase.table("ai_suggestions")
            .select("*")
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

        logger.debug(f"GET /ai/suggestions - {len(latest)} suggestion(s)")
        return AISuggestionsResponse(
            suggestions=latest,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        logger.error(f"GET /ai/suggestions failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch suggestions: {e}")


@app.post("/ai/suggestions/generate", response_model=AISuggestionsResponse)
def generate_ai_suggestions():
    """Generate fresh AI priority suggestions for all active assignments.

    Synchronous: waits for Groq (~3–8s). Saves results to ai_suggestions table.
    """
    logger.info("POST /ai/suggestions/generate")

    assignments = _fetch_active_assignments()
    if not assignments:
        return AISuggestionsResponse(
            suggestions=[],
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    prefs = _fetch_user_preferences()
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
        saved = supabase.table("ai_suggestions").insert(rows).execute()
        logger.info(f"POST /ai/suggestions/generate - saved {len(saved.data)} suggestion(s)")
    except Exception as e:
        logger.error(f"POST /ai/suggestions/generate - DB insert failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save suggestions: {e}")

    return AISuggestionsResponse(suggestions=saved.data, generated_at=now_iso)


@app.post("/ai/briefing/generate", response_model=AIBriefingResponse)
def generate_ai_briefing():
    """Generate a natural-language daily plan briefing (~2s)."""
    logger.info("POST /ai/briefing/generate")

    assignments = _fetch_active_assignments()
    if not assignments:
        return AIBriefingResponse(
            briefing="No active assignments found. Enjoy the free time!",
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    prefs = _fetch_user_preferences()
    try:
        briefing = ai_service.generate_briefing(assignments, prefs)
    except Exception as e:
        raise _ai_error_to_http(e)

    return AIBriefingResponse(
        briefing=briefing,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/ai/chat")
async def ai_chat(req: AIChatRequest):
    """Streaming SSE chat endpoint. Returns text/event-stream.

    Each SSE event: data: {"delta": "..."}\n\n
    Final event:   data: [DONE]\n\n
    Error event:   data: {"error": "...", "code": N}\n\n
    """
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages list cannot be empty")

    assignments = _fetch_active_assignments()
    prefs = _fetch_user_preferences()
    messages_dicts = [{"role": m.role, "content": m.content} for m in req.messages]

    logger.info(f"POST /ai/chat - {len(req.messages)} message(s)")

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
def ai_apply_plan(req: AIApplyPlanRequest):
    """Extract a study plan from the conversation and write planned_start to assignments.

    Returns: {updated: N, assignments: [{id, planned_start}]}
    """
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages list cannot be empty")

    logger.info(f"POST /ai/apply-plan - {len(req.messages)} message(s)")

    assignments = _fetch_active_assignments()
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
            supabase.table("assignments").update(
                {"planned_start": planned_start}
            ).eq("id", aid).execute()
            updated.append({"id": aid, "planned_start": planned_start})
        except Exception as e:
            logger.warning(f"POST /ai/apply-plan - failed to update {aid}: {e}")

    logger.info(f"POST /ai/apply-plan - updated {len(updated)} assignment(s)")
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
def push_subscribe(sub: PushSubscription):
    """Save a browser push subscription (upsert by endpoint)."""
    logger.info(f"POST /push/subscribe - {sub.endpoint[:60]}…")
    try:
        existing = supabase.table("push_subscriptions").select("id").eq("endpoint", sub.endpoint).execute()
        row = {
            "endpoint": sub.endpoint,
            "p256dh": sub.keys.get("p256dh", ""),
            "auth": sub.keys.get("auth", ""),
        }
        if existing.data:
            supabase.table("push_subscriptions").update(row).eq("endpoint", sub.endpoint).execute()
        else:
            supabase.table("push_subscriptions").insert(row).execute()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"POST /push/subscribe failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/push/subscribe")
def push_unsubscribe(sub: PushSubscription):
    """Remove a push subscription."""
    try:
        supabase.table("push_subscriptions").delete().eq("endpoint", sub.endpoint).execute()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/push/send-deadline-reminders")
def send_deadline_reminders():
    """Send push notifications for assignments due within 24 hours.

    Called on demand or by an external cron. Only sends if subscriptions exist.
    """
    logger.info("POST /push/send-deadline-reminders")

    vapid_private = os.getenv("VAPID_PRIVATE_KEY", "").replace("\\n", "\n")
    vapid_public = os.getenv("VAPID_PUBLIC_KEY", "")
    vapid_contact = os.getenv("VAPID_CONTACT", "mailto:admin@campusai.app")

    if not vapid_private or not vapid_public:
        raise HTTPException(status_code=503, detail="VAPID keys not configured.")

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        raise HTTPException(status_code=503, detail="pywebpush not installed.")

    # Fetch subscriptions
    subs_res = supabase.table("push_subscriptions").select("*").execute()
    subscriptions = subs_res.data or []
    if not subscriptions:
        return {"sent": 0, "message": "No subscribers."}

    # Find assignments due in the next 24 hours
    now = datetime.now(timezone.utc)
    in_24h = (now + timedelta(hours=24)).isoformat()
    due_soon = (
        supabase.table("assignments")
        .select("title, course_name, due_date")
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
        supabase.table("push_subscriptions").delete().eq("endpoint", endpoint).execute()

    logger.info(f"POST /push/send-deadline-reminders — sent {sent}, removed {len(stale)} stale")
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
