import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from supabase import create_client

from sync_service import sync_service
import auth_store
import canvas_auth_store

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
def get_assignments():
    response = supabase.table("assignments").select("*").order("due_date").execute()
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
