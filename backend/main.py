import os
import json
import logging
import uuid as _uuid
import xml.etree.ElementTree as ET
import urllib.parse
import time
from fastapi import FastAPI, HTTPException, Query, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from supabase import create_client

import jwt as pyjwt  # PyJWT

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

# CAS redirect login state
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
CAS_BASE = "https://cas.byu.edu/cas"
LS_BASE = "https://learningsuite.byu.edu"
_cas_states: dict = {}   # state_token → {user_id, task_id, service_url}
_pgt_store: dict = {}    # pgtiou → pgt_id

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


# ============== AUTH ROUTES ==============
# Handle browser-based BYU authentication

@app.post("/auth/browser-login")
def browser_login(user_id: str = Depends(get_current_user)):
    """Start browser-based BYU login.

    Opens a browser window to BYU's login page where the user
    authenticates directly. We never see their password.
    """
    import threading
    from scraper.learning_suite_scraper import LearningSuiteScraper

    # Check if already authenticating
    if auth_store.is_authenticated(user_id):
        return {"success": True, "message": "Already authenticated", "task_id": None}

    task_id = auth_store.create_browser_auth_task()
    logger.info(f"POST /auth/browser-login user={user_id[:8]} - Starting browser auth task: {task_id}")

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

                    # Store cookies + URL + web storage for this user, then close the visible browser
                    auth_store.set_session_data(user_id, cookies, dynamic_base_url)
                    auth_store.set_web_storage(user_id, local_storage, session_storage)
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


class LSCredentialsRequest(BaseModel):
    netid: str
    password: str


@app.post("/auth/ls-credentials")
def ls_credentials_login(req: LSCredentialsRequest, user_id: str = Depends(get_current_user)):
    """Login to Learning Suite using BYU credentials in headless Chrome.

    Automates the CAS login form, then waits for the user to approve a Duo
    push notification on their phone. The password is used only to fill the
    login form and is cleared from memory immediately after — it is never
    stored anywhere.
    """
    import threading
    import re
    import time
    from scraper.learning_suite_scraper import LearningSuiteScraper
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    task_id = auth_store.create_browser_auth_task()
    netid = req.netid.strip()
    password = req.password  # captured in closure; cleared below

    logger.info(f"POST /auth/ls-credentials user={user_id[:8]} netid={netid} - task {task_id[:8]}")

    def run_credentials_login(pwd: str):
        scraper = None
        try:
            auth_store.update_browser_auth_status(task_id, auth_store.BrowserAuthStatus.OPENING)
            scraper = LearningSuiteScraper(headless=True)
            scraper._setup_driver()

            auth_store.update_browser_auth_status(task_id, auth_store.BrowserAuthStatus.WAITING_FOR_LOGIN)

            # Navigate to LS — redirects to BYU CAS login
            scraper.driver.get("https://learningsuite.byu.edu")

            # Wait for CAS username field
            wait = WebDriverWait(scraper.driver, 20)
            try:
                username_field = wait.until(EC.presence_of_element_located((By.ID, "username")))
            except Exception:
                # Try name attribute as fallback
                username_field = wait.until(EC.presence_of_element_located((By.NAME, "username")))

            username_field.clear()
            username_field.send_keys(netid)

            try:
                password_field = scraper.driver.find_element(By.ID, "password")
            except Exception:
                password_field = scraper.driver.find_element(By.NAME, "password")

            password_field.clear()
            password_field.send_keys(pwd)
            pwd = ""  # Clear password from local variable immediately

            password_field.submit()

            # Submitted credentials — now wait for Duo
            auth_store.update_browser_auth_status(task_id, auth_store.BrowserAuthStatus.WAITING_FOR_MFA)
            logger.info(f"Credentials login [{task_id[:8]}] - Credentials submitted, monitoring for Duo...")

            def _capture_and_finish():
                """Extract cookies from the current LS session and mark auth complete."""
                dynamic_base_url = scraper._extract_dynamic_base_url()
                cookies = scraper.driver.get_cookies()
                local_storage, session_storage = {}, {}
                try:
                    local_storage = scraper.driver.execute_script(
                        "var items = {}; for (var i = 0; i < localStorage.length; i++) {"
                        " var k = localStorage.key(i); items[k] = localStorage.getItem(k); } return items;"
                    ) or {}
                except Exception:
                    pass
                try:
                    session_storage = scraper.driver.execute_script(
                        "var items = {}; for (var i = 0; i < sessionStorage.length; i++) {"
                        " var k = sessionStorage.key(i); items[k] = sessionStorage.getItem(k); } return items;"
                    ) or {}
                except Exception:
                    pass
                auth_store.set_session_data(user_id, cookies, dynamic_base_url)
                auth_store.set_web_storage(user_id, local_storage, session_storage)
                scraper.close()
                auth_store.update_browser_auth_status(task_id, auth_store.BrowserAuthStatus.AUTHENTICATED)

            max_wait = 30  # seconds to wait before switching to passcode mode
            waited = 0
            on_duo_page = False

            while waited < max_wait:
                current_url = scraper.driver.current_url

                if re.match(r'https://learningsuite\.byu\.edu/\.[A-Za-z0-9]+', current_url):
                    logger.info(f"Credentials login [{task_id[:8]}] - Login successful (push approved)!")
                    _capture_and_finish()
                    return

                if 'duo' in current_url.lower() or 'duosecurity' in current_url.lower():
                    on_duo_page = True
                    break

                # Check for wrong password
                try:
                    page_src = scraper.driver.page_source.lower()
                    if "invalid credentials" in page_src or "incorrect" in page_src:
                        scraper.close()
                        auth_store.update_browser_auth_status(
                            task_id, auth_store.BrowserAuthStatus.FAILED,
                            "Incorrect NetID or password. Please try again."
                        )
                        return
                except Exception:
                    pass

                time.sleep(2)
                waited += 2

            # On Duo page (or timed out waiting) — switch to passcode mode
            if on_duo_page or waited >= max_wait:
                logger.info(f"Credentials login [{task_id[:8]}] - Duo page detected, requesting passcode from user")
                auth_store.update_browser_auth_status(task_id, auth_store.BrowserAuthStatus.WAITING_FOR_DUO_PASSCODE)

                # Block until the user submits their passcode (up to 5 minutes)
                passcode = auth_store.wait_for_duo_passcode(task_id, timeout=300)

                if not passcode:
                    scraper.close()
                    auth_store.update_browser_auth_status(
                        task_id, auth_store.BrowserAuthStatus.FAILED,
                        "Timed out waiting for Duo passcode."
                    )
                    return

                logger.info(f"Credentials login [{task_id[:8]}] - Got passcode, entering in Duo...")

                # Navigate Duo UI to passcode entry
                try:
                    driver = scraper.driver
                    time.sleep(1)

                    # Try clicking "Other options" or "Use a passcode"
                    for xpath in [
                        "//*[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'other option')]",
                        "//*[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'passcode')]",
                        "//*[@data-testid='other-options-link']",
                    ]:
                        try:
                            el = driver.find_element(By.XPATH, xpath)
                            el.click()
                            time.sleep(1)
                            break
                        except Exception:
                            pass

                    # Find and fill passcode input
                    passcode_input = None
                    for selector in [
                        "input[data-testid='passcode-input']",
                        "input[name='passcode']",
                        "input[type='tel']",
                        "input[type='text']",
                    ]:
                        try:
                            passcode_input = WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                            )
                            break
                        except Exception:
                            pass

                    if passcode_input:
                        passcode_input.clear()
                        passcode_input.send_keys(passcode)
                        time.sleep(0.5)
                        # Submit
                        for btn_selector in [
                            "button[data-testid='passcode-submit']",
                            "button[type='submit']",
                        ]:
                            try:
                                driver.find_element(By.CSS_SELECTOR, btn_selector).click()
                                break
                            except Exception:
                                pass
                        else:
                            passcode_input.submit()
                    else:
                        logger.error(f"Credentials login [{task_id[:8]}] - Could not find Duo passcode input")
                        scraper.close()
                        auth_store.update_browser_auth_status(
                            task_id, auth_store.BrowserAuthStatus.FAILED,
                            "Could not find Duo passcode input. Please try again."
                        )
                        return

                except Exception as e:
                    logger.error(f"Credentials login [{task_id[:8]}] - Duo passcode entry failed: {e}")
                    scraper.close()
                    auth_store.update_browser_auth_status(
                        task_id, auth_store.BrowserAuthStatus.FAILED, str(e)
                    )
                    return

                # Wait for redirect to LS after passcode entry
                for _ in range(60):
                    time.sleep(2)
                    current_url = scraper.driver.current_url
                    if re.match(r'https://learningsuite\.byu\.edu/\.[A-Za-z0-9]+', current_url):
                        logger.info(f"Credentials login [{task_id[:8]}] - Login successful (passcode)!")
                        _capture_and_finish()
                        return

                scraper.close()
                auth_store.update_browser_auth_status(
                    task_id, auth_store.BrowserAuthStatus.FAILED,
                    "Passcode was incorrect or login timed out. Please try again."
                )

        except Exception as e:
            logger.error(f"Credentials login [{task_id[:8]}] failed: {e}")
            if scraper:
                try:
                    scraper.close()
                except Exception:
                    pass
            auth_store.update_browser_auth_status(
                task_id, auth_store.BrowserAuthStatus.FAILED, str(e)
            )

    thread = threading.Thread(target=run_credentials_login, args=(password,), daemon=True)
    thread.start()

    return {"success": True, "task_id": task_id, "message": "Logging in..."}


class DuoPasscodeRequest(BaseModel):
    code: str


@app.post("/auth/ls-duo-passcode/{task_id}")
def submit_duo_passcode(task_id: str, req: DuoPasscodeRequest, user_id: str = Depends(get_current_user)):
    """Accept the user's Duo passcode from the frontend and forward it to the waiting login thread."""
    code = req.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="Passcode is required")
    auth_store.set_duo_passcode(task_id, code)
    logger.info(f"POST /auth/ls-duo-passcode task={task_id[:8]} - Passcode received")
    return {"success": True}


@app.get("/auth/browser-status/{task_id}")
def browser_auth_status(task_id: str, user_id: str = Depends(get_current_user)):
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
def auth_status(user_id: str = Depends(get_current_user)):
    """Check if user is authenticated (LS and/or Canvas)."""
    is_auth = auth_store.is_authenticated(user_id)
    return AuthStatusResponse(
        authenticated=is_auth,
        netid=None,  # We don't store netid with browser auth
        canvas_connected=canvas_auth_store.is_connected(user_id),
    )


@app.post("/auth/logout")
def logout(user_id: str = Depends(get_current_user)):
    """Clear authentication and close browser session."""
    logger.info(f"POST /auth/logout user={user_id[:8]}")
    auth_store.clear_authentication(user_id)
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


# ============== BYU CAS REDIRECT LOGIN ==============

@app.post("/auth/byu-login-start")
def byu_login_start(user_id: str = Depends(get_current_user)):
    """Create a CAS login URL and return it for the frontend to open in a new tab.

    The user is redirected to BYU's real CAS login page in a new tab. After they
    authenticate, BYU redirects their browser to our /auth/cas-callback endpoint,
    which uses a CAS proxy ticket to establish a server-side LS session.
    """
    state = str(_uuid.uuid4())
    task_id = auth_store.create_browser_auth_task()

    service_url = f"{BACKEND_URL}/auth/cas-callback?state={state}"
    pgt_url = f"{BACKEND_URL}/auth/cas-pgt"

    _cas_states[state] = {
        "user_id": user_id,
        "task_id": task_id,
        "service_url": service_url,
    }

    cas_url = (
        f"{CAS_BASE}/login"
        f"?service={urllib.parse.quote(service_url, safe='')}"
        f"&pgtUrl={urllib.parse.quote(pgt_url, safe='')}"
    )

    logger.info(f"POST /auth/byu-login-start user={user_id[:8]} state={state[:8]} task={task_id[:8]}")
    return {"task_id": task_id, "cas_url": cas_url}


@app.get("/auth/cas-pgt")
def cas_pgt_callback(pgtId: str = Query(None), pgtIou: str = Query(None)):
    """Called by BYU's CAS server (not the browser) to deliver a Proxy Granting Ticket.

    CAS calls this endpoint with pgtId (the actual PGT) and pgtIou (a correlation ID)
    as query parameters immediately after validating the service ticket. We store
    the pgtId keyed by pgtIou so the callback handler can look it up.
    """
    if pgtId and pgtIou:
        _pgt_store[pgtIou] = pgtId
        logger.info(f"CAS PGT callback: stored PGT for pgtIou {pgtIou[:16]}...")
    # CAS requires HTTP 200 with any body to confirm receipt
    return {"status": "ok"}


@app.get("/auth/cas-callback")
def cas_callback(ticket: str = Query(None), state: str = Query(None)):
    """BYU CAS redirects the user's browser here after successful authentication.

    1. Validates the service ticket via CAS proxyValidate (also triggers PGT delivery)
    2. Waits for the PGT to arrive via /auth/cas-pgt
    3. Requests a proxy ticket for Learning Suite
    4. Uses the proxy ticket to establish an LS session (server-to-server)
    5. Stores cookies in auth_store and returns a success page that auto-closes
    """
    import re
    import requests as _req

    def _page(title: str, body: str, auto_close: bool = False, is_error: bool = False):
        color = "#dc2626" if is_error else "#4ade80"
        icon = "✗" if is_error else "✓"
        close_script = "<script>setTimeout(function(){window.close();},2000);</script>" if auto_close else ""
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><title>CampusAI</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#0f172a;color:#f8fafc">
<div style="text-align:center;max-width:420px;padding:2rem">
  <div style="font-size:3rem;margin-bottom:1rem;color:{color}">{icon}</div>
  <p style="font-size:1.2rem;font-weight:600;margin:0 0 0.5rem">{title}</p>
  <p style="color:#94a3b8;font-size:0.875rem;margin:0">{body}</p>
</div>{close_script}</body></html>""")

    if not ticket or not state:
        return _page("Invalid Request", "Missing ticket or state. Please close this tab and try again.", is_error=True)

    state_data = _cas_states.get(state)
    if not state_data:
        return _page("Session Expired", "This login session has expired. Please close this tab and try again.", is_error=True)

    user_id = state_data["user_id"]
    task_id = state_data["task_id"]
    service_url = state_data["service_url"]
    pgt_url = f"{BACKEND_URL}/auth/cas-pgt"
    ns = {"cas": "http://www.yale.edu/tp/cas"}

    # Step 1 — Validate service ticket with CAS proxyValidate
    validate_url = (
        f"{CAS_BASE}/proxyValidate"
        f"?service={urllib.parse.quote(service_url, safe='')}"
        f"&ticket={urllib.parse.quote(ticket, safe='')}"
        f"&pgtUrl={urllib.parse.quote(pgt_url, safe='')}"
    )
    try:
        cas_resp = _req.get(validate_url, timeout=15)
        root = ET.fromstring(cas_resp.text)
        logger.info(f"CAS proxyValidate response (first 400 chars): {cas_resp.text[:400]}")
    except Exception as e:
        logger.error(f"CAS validate request failed: {e}")
        auth_store.update_browser_auth_status(task_id, auth_store.BrowserAuthStatus.FAILED, str(e))
        return _page("CAS Error", f"Could not reach BYU CAS: {e}", is_error=True)

    success_el = root.find(".//cas:authenticationSuccess", ns)
    if success_el is None:
        fail_el = root.find(".//cas:authenticationFailure", ns)
        msg = (fail_el.text or "").strip() if fail_el is not None else "Authentication failed"
        auth_store.update_browser_auth_status(task_id, auth_store.BrowserAuthStatus.FAILED, msg)
        logger.error(f"CAS authentication failed: {msg}")
        return _page("Login Failed", msg, is_error=True)

    # Step 2 — Wait up to 5 seconds for PGT to arrive via /auth/cas-pgt
    pgtiou_el = success_el.find("cas:proxyGrantingTicket", ns)
    pgtiou = pgtiou_el.text.strip() if pgtiou_el is not None else None

    pgt_id = None
    if pgtiou:
        for _ in range(10):
            pgt_id = _pgt_store.get(pgtiou)
            if pgt_id:
                break
            time.sleep(0.5)

    if not pgt_id:
        logger.warning(f"No PGT received (pgtiou={'present' if pgtiou else 'absent'}) — proxy tickets unavailable")
        auth_store.update_browser_auth_status(
            task_id, auth_store.BrowserAuthStatus.FAILED,
            "CAS proxy tickets unavailable for this service. Contact support."
        )
        return _page(
            "Configuration Required",
            "BYU CAS proxy tickets are not enabled for this app. Please contact support.",
            is_error=True
        )

    # Step 3 — Request a proxy ticket for Learning Suite
    proxy_url = (
        f"{CAS_BASE}/proxy"
        f"?targetService={urllib.parse.quote(LS_BASE, safe='')}"
        f"&pgt={urllib.parse.quote(pgt_id, safe='')}"
    )
    try:
        proxy_resp = _req.get(proxy_url, timeout=15)
        proxy_root = ET.fromstring(proxy_resp.text)
        logger.info(f"CAS proxy response: {proxy_resp.text[:400]}")
        pt_el = proxy_root.find(".//cas:proxyTicket", ns)
        pt = pt_el.text.strip() if pt_el is not None else None
    except Exception as e:
        logger.error(f"CAS proxy ticket request failed: {e}")
        auth_store.update_browser_auth_status(task_id, auth_store.BrowserAuthStatus.FAILED, str(e))
        return _page("Proxy Ticket Failed", f"Could not get Learning Suite access token: {e}", is_error=True)

    if not pt:
        auth_store.update_browser_auth_status(task_id, auth_store.BrowserAuthStatus.FAILED, "No proxy ticket in CAS response")
        return _page("Proxy Ticket Failed", "CAS did not return a proxy ticket for Learning Suite.", is_error=True)

    # Step 4 — Use proxy ticket to establish an LS session (server-to-server)
    session = _req.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"})
    try:
        ls_resp = session.get(
            f"{LS_BASE}/",
            params={"ticket": pt},
            allow_redirects=True,
            timeout=20,
        )
        final_url = ls_resp.url
        logger.info(f"LS CAS auth: status={ls_resp.status_code} final_url={final_url}")

        if re.match(r'https://learningsuite\.byu\.edu/\.[A-Za-z0-9]+', final_url):
            cookies_list = [
                {
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain or ".learningsuite.byu.edu",
                    "path": c.path or "/",
                    "secure": c.secure,
                }
                for c in session.cookies
            ]
            auth_store.set_session_data(user_id, cookies_list, final_url.rstrip("/"))
            auth_store.update_browser_auth_status(task_id, auth_store.BrowserAuthStatus.AUTHENTICATED)
            _cas_states.pop(state, None)
            _pgt_store.pop(pgtiou, None)
            logger.info(f"CAS login succeeded for user={user_id[:8]} — {len(cookies_list)} cookies stored")
            return _page(
                "Connected to Learning Suite!",
                "You're signed in. This tab will close automatically.",
                auto_close=True
            )
        else:
            logger.error(f"LS CAS auth ended at unexpected URL: {final_url}")
            auth_store.update_browser_auth_status(
                task_id, auth_store.BrowserAuthStatus.FAILED,
                f"LS redirect ended at unexpected URL: {final_url}"
            )
            return _page("Connection Failed", "Could not establish a Learning Suite session. Please try again.", is_error=True)

    except Exception as e:
        logger.error(f"LS session establishment failed: {e}")
        auth_store.update_browser_auth_status(task_id, auth_store.BrowserAuthStatus.FAILED, str(e))
        return _page("Connection Failed", f"Error connecting to Learning Suite: {e}", is_error=True)


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

    response = supabase_service.table("assignments").update(
        update_data
    ).eq("id", assignment_id).eq("user_id", user_id).execute()

    if not response.data:
        raise HTTPException(status_code=404, detail="Assignment not found")

    return {"assignment": response.data[0]}


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
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
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
