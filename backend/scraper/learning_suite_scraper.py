"""
Learning Suite Scraper for BYU

This module handles:
- BYU CAS authentication via Selenium
- Course list extraction
- Assignment scraping from Grades and Exams tabs
- Status mapping from Learning Suite to CampusAI
- Change detection and database updates
"""

import os
import re
import time
import logging
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException
)
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

from dotenv import load_dotenv
from supabase import create_client
import html

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LearningSuiteScraper:
    """Scraper for BYU Learning Suite assignments."""

    LEARNING_SUITE_URL = "https://learningsuite.byu.edu"
    CAS_LOGIN_URL = "https://cas.byu.edu"
    DEBUG_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "debug.html")

    # Status mapping from Learning Suite button text to CampusAI status
    # IMPORTANT: Only map to 'submitted' when we're CERTAIN the assignment is done
    STATUS_MAPPING = {
        # In Progress - quiz/exam that was started and saved
        'continue': 'in_progress',
        'continue exam': 'in_progress',
        'resume': 'in_progress',

        # Not Started - available but not begun
        'begin': 'not_started',
        'begin exam': 'not_started',
        'start': 'not_started',
        'open': 'not_started',
        'submit': 'not_started',  # File upload - can't track if done
        'take': 'not_started',

        # Submitted - ONLY when we're certain it's been turned in
        'completed': 'submitted',
        'graded': 'submitted',
        'resubmit': 'submitted',  # Can resubmit means already submitted once

        # Closed/unavailable
        'closed': 'not_started',  # Missed it but still mark as not started
        'unavailable': 'unavailable',
    }

    # These button texts are AMBIGUOUS - 'view' can mean view results OR view assignment
    # Default to not_started for safety (unless has_score overrides)
    AMBIGUOUS_BUTTONS = {'view', 'view/submit'}

    # Session error indicators that suggest we need to re-authenticate
    SESSION_EXPIRED_INDICATORS = [
        "session expired",
        "please sign in",
        "log in to continue",
        "your session has timed out",
        "session has ended",
        "authentication required",
    ]

    def __init__(self, headless: bool = False):
        """Initialize the scraper.

        Args:
            headless: Whether to run Chrome in headless mode
        """
        self.driver = None
        self.headless = headless
        self.supabase = None
        self.dynamic_base_url = None  # Set after login to include session segment (e.g., /.DaEo)
        self._injected_cookies = []  # Store cookies for re-injection
        self._injected_base_url = ""  # Store base URL for re-injection
        self._local_storage = {}  # Store localStorage for re-injection
        self._session_storage = {}  # Store sessionStorage for re-injection
        self._last_keepalive = None  # Track last keep-alive time
        self._session_refresh_count = 0  # Track how many times we've refreshed
        self._max_session_refreshes = 3  # Max refreshes before giving up
        self._setup_supabase()

    def _setup_supabase(self):
        """Set up Supabase client."""
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if url and key:
            self.supabase = create_client(url, key)
            logger.info("Supabase client initialized")
        else:
            logger.warning("Supabase credentials not found - database updates disabled")

    def _extract_dynamic_base_url(self) -> str:
        """Extract the dynamic base URL from the current URL after login.

        Learning Suite uses dynamic session segments in URLs (e.g., /.DaEo).
        After login, the URL looks like: https://learningsuite.byu.edu/.DaEo/student/top
        We need to extract: https://learningsuite.byu.edu/.DaEo

        Returns:
            The dynamic base URL including the session segment
        """
        current_url = self.driver.current_url
        logger.info(f"Extracting dynamic base from URL: {current_url}")

        # Match the pattern: https://learningsuite.byu.edu/.<segment>
        # The session segment starts with /. followed by alphanumeric characters
        match = re.match(r'(https://learningsuite\.byu\.edu/\.[A-Za-z0-9]+)', current_url)
        if match:
            base_url = match.group(1)
            logger.info(f"Extracted dynamic base URL: {base_url}")
            return base_url

        # Fallback: if no session segment found, use the static URL
        logger.warning(f"No dynamic session segment found in URL, using static base")
        return self.LEARNING_SUITE_URL

    def _get_base_url(self) -> str:
        """Get the base URL to use for navigation.

        Returns the dynamic base URL if available (after login),
        otherwise falls back to the static LEARNING_SUITE_URL.

        Returns:
            Base URL string to use for constructing navigation URLs
        """
        if self.dynamic_base_url:
            return self.dynamic_base_url
        return self.LEARNING_SUITE_URL

    def _sanitize_url(self, url: str, cid: str = None) -> str:
        """Sanitize a Learning Suite URL to remove session segments.

        Session segments like /.9dem or /.iMnE expire and cause error pages.
        This converts URLs to use the static base URL with the course CID.

        Args:
            url: The URL to sanitize
            cid: Optional course ID to include in the URL

        Returns:
            Sanitized URL without session segment
        """
        if not url:
            return url

        # Remove session segment (pattern: /.[A-Za-z0-9]+)
        # Convert: https://learningsuite.byu.edu/.9dem/assignment/XXX
        # To:      https://learningsuite.byu.edu/cid-YYY/assignment/XXX (if cid provided)
        # Or:      https://learningsuite.byu.edu/assignment/XXX (if no cid)

        # Extract the path after the session segment
        match = re.search(r'https://learningsuite\.byu\.edu/\.[A-Za-z0-9]+(/.*)', url)
        if match:
            path = match.group(1)
            # If we have a cid and the path doesn't already have one, add it
            if cid and 'cid-' not in path:
                return f"{self.LEARNING_SUITE_URL}/cid-{cid}{path}"
            return f"{self.LEARNING_SUITE_URL}{path}"

        return url

    def _clean_description(self, description: str) -> str:
        """Clean HTML tags and entities from a description string.

        Args:
            description: Raw description that may contain HTML

        Returns:
            Cleaned description text
        """
        if not description:
            return description

        # First decode HTML entities (&amp; -> &, &#39; -> ', &nbsp; -> space)
        cleaned = html.unescape(description)

        # Remove HTML tags
        cleaned = re.sub(r'<[^>]+>', '', cleaned)

        # Clean up extra whitespace from removed tags
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        # Truncate if too long
        if len(cleaned) > 500:
            cleaned = cleaned[:500] + "..."

        return cleaned

    def _setup_driver(self):
        """Set up Chrome WebDriver."""
        logger.info("Setting up Chrome options...")
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")  # Use new headless mode
            logger.info("Running in headless mode")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        # Reduce logging noise
        options.add_argument("--log-level=3")
        options.add_experimental_option('excludeSwitches', ['enable-logging'])

        # Anti-detection: make headless browser look like a regular browser
        if self.headless:
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        logger.info("Installing/finding ChromeDriver...")
        service = Service(ChromeDriverManager().install())
        logger.info("Starting Chrome browser...")
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.implicitly_wait(10)

        # Remove webdriver flag that sites can detect
        if self.headless:
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        logger.info("Chrome WebDriver initialized successfully")

    def inject_cookies(self, cookies: list, base_url: str,
                       local_storage: dict = None, session_storage: dict = None) -> bool:
        """Inject cookies from a previous session into this browser.

        Used to transfer an authenticated session from a visible browser
        to a headless browser for background scraping.

        Args:
            cookies: List of cookie dicts from driver.get_cookies()
            base_url: The dynamic base URL (e.g., https://learningsuite.byu.edu/.DaEo)
            local_storage: Optional localStorage data to inject
            session_storage: Optional sessionStorage data to inject

        Returns:
            True if session is valid after injection, False otherwise
        """
        try:
            # Store for potential re-injection later
            self._injected_cookies = cookies
            self._injected_base_url = base_url
            self._local_storage = local_storage or {}
            self._session_storage = session_storage or {}
            self._last_keepalive = time.time()

            # Navigate to the domain first (required to set cookies)
            self.driver.get(self.LEARNING_SUITE_URL)
            time.sleep(1)

            # Inject each cookie - keep all fields except truly problematic ones
            # Fields like 'expiry', 'sameSite' are important for session validity
            injected_count = 0
            for cookie in cookies:
                # Only remove fields that Selenium cannot handle
                # Keep: name, value, domain, path, secure, httpOnly, expiry, sameSite
                fields_to_remove = {'sessionId', 'storeId'}
                clean_cookie = {k: v for k, v in cookie.items()
                                if k not in fields_to_remove}

                # Fix sameSite value if present - Selenium requires specific casing
                if 'sameSite' in clean_cookie:
                    same_site = str(clean_cookie['sameSite']).capitalize()
                    if same_site not in ('Strict', 'Lax', 'None'):
                        del clean_cookie['sameSite']
                    else:
                        clean_cookie['sameSite'] = same_site

                try:
                    self.driver.add_cookie(clean_cookie)
                    injected_count += 1
                except Exception as e:
                    # If adding with extra fields fails, try minimal cookie
                    minimal_cookie = {k: v for k, v in cookie.items()
                                      if k in ('name', 'value', 'domain', 'path', 'secure', 'httpOnly')}
                    try:
                        self.driver.add_cookie(minimal_cookie)
                        injected_count += 1
                    except Exception as e2:
                        logger.debug(f"Skipped cookie {cookie.get('name')}: {e2}")

            logger.info(f"Injected {injected_count}/{len(cookies)} cookies")

            # Set the dynamic base URL
            self.dynamic_base_url = base_url

            # Inject localStorage and sessionStorage data
            if self._local_storage:
                self._inject_web_storage(self._local_storage, 'localStorage')
            if self._session_storage:
                self._inject_web_storage(self._session_storage, 'sessionStorage')

            # Verify the session works by navigating to the base URL
            self.driver.get(base_url)
            time.sleep(2)

            current_url = self.driver.current_url
            # If we're redirected to CAS login, the session is invalid
            if 'cas.byu.edu' in current_url:
                logger.warning("Cookie injection failed -- redirected to CAS login")
                return False

            # Also check for Duo or other auth redirects
            if any(x in current_url.lower() for x in ['duo', 'authenticate', 'saml', 'idp']):
                logger.warning(f"Cookie injection failed -- redirected to auth page: {current_url}")
                return False

            # Deep verification: try navigating to student top page
            student_url = f"{base_url}/student/top"
            self.driver.get(student_url)
            time.sleep(2)

            current_url = self.driver.current_url
            if 'cas.byu.edu' in current_url or 'duo' in current_url.lower():
                logger.warning("Deep session verification failed -- redirected to login")
                return False

            # Check page content for session expiry messages
            if not self._check_session_valid():
                logger.warning("Session appears invalid after deep verification")
                return False

            logger.info(f"Cookie injection successful, verified at: {current_url}")
            return True

        except Exception as e:
            logger.error(f"Cookie injection error: {e}")
            return False

    def _inject_web_storage(self, storage_data: dict, storage_type: str):
        """Inject localStorage or sessionStorage data into the browser.

        Args:
            storage_data: Dictionary of key-value pairs to inject
            storage_type: Either 'localStorage' or 'sessionStorage'
        """
        if not storage_data:
            return

        try:
            for key, value in storage_data.items():
                # Escape the value for JavaScript
                escaped_value = str(value).replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
                escaped_key = str(key).replace("\\", "\\\\").replace("'", "\\'")
                self.driver.execute_script(
                    f"{storage_type}.setItem('{escaped_key}', '{escaped_value}');"
                )
            logger.info(f"Injected {len(storage_data)} {storage_type} items")
        except Exception as e:
            logger.debug(f"Could not inject {storage_type}: {e}")

    def _refresh_session(self) -> bool:
        """Attempt to refresh the session by re-injecting cookies.

        Called when a session expiry is detected mid-scrape.

        Returns:
            True if session was successfully refreshed, False otherwise
        """
        self._session_refresh_count += 1
        if self._session_refresh_count > self._max_session_refreshes:
            logger.error(f"Session refresh limit reached ({self._max_session_refreshes}), giving up")
            return False

        logger.warning(f"Attempting session refresh (attempt {self._session_refresh_count}/{self._max_session_refreshes})...")

        if not self._injected_cookies or not self._injected_base_url:
            logger.error("No stored cookies/URL for session refresh")
            return False

        try:
            # Clear existing cookies
            self.driver.delete_all_cookies()
            time.sleep(1)

            # Re-navigate to domain
            self.driver.get(self.LEARNING_SUITE_URL)
            time.sleep(1)

            # Re-inject all cookies
            injected = 0
            for cookie in self._injected_cookies:
                fields_to_remove = {'sessionId', 'storeId'}
                clean_cookie = {k: v for k, v in cookie.items()
                                if k not in fields_to_remove}

                if 'sameSite' in clean_cookie:
                    same_site = str(clean_cookie['sameSite']).capitalize()
                    if same_site not in ('Strict', 'Lax', 'None'):
                        del clean_cookie['sameSite']
                    else:
                        clean_cookie['sameSite'] = same_site

                try:
                    self.driver.add_cookie(clean_cookie)
                    injected += 1
                except Exception:
                    minimal = {k: v for k, v in cookie.items()
                               if k in ('name', 'value', 'domain', 'path', 'secure', 'httpOnly')}
                    try:
                        self.driver.add_cookie(minimal)
                        injected += 1
                    except Exception:
                        pass

            logger.info(f"Session refresh: re-injected {injected}/{len(self._injected_cookies)} cookies")

            # Re-inject web storage
            if self._local_storage:
                self._inject_web_storage(self._local_storage, 'localStorage')
            if self._session_storage:
                self._inject_web_storage(self._session_storage, 'sessionStorage')

            # Navigate to base URL and verify
            self.driver.get(self._injected_base_url)
            time.sleep(2)

            current_url = self.driver.current_url
            if 'cas.byu.edu' in current_url or 'duo' in current_url.lower():
                logger.error(f"Session refresh failed -- still redirected to login: {current_url}")
                return False

            if not self._check_session_valid():
                logger.error("Session refresh failed -- session still invalid")
                return False

            # Re-extract dynamic base URL (session segment may have changed)
            new_base = self._extract_dynamic_base_url()
            if new_base and new_base != self.LEARNING_SUITE_URL:
                self.dynamic_base_url = new_base
                logger.info(f"Session refresh: updated base URL to {new_base}")

            self._last_keepalive = time.time()
            logger.info("Session refresh successful!")
            return True

        except Exception as e:
            logger.error(f"Session refresh error: {e}")
            return False

    def _keepalive(self):
        """Send a keep-alive request to prevent session timeout.

        Navigates to the Learning Suite home page to refresh the session timer.
        Should be called periodically between courses during long scrapes.
        """
        try:
            now = time.time()
            # Only send keep-alive if more than 60 seconds since last one
            if self._last_keepalive and (now - self._last_keepalive) < 60:
                return

            logger.info("Sending session keep-alive...")
            # Touch the base URL to refresh the session timer
            self.driver.get(f"{self._get_base_url()}/student/top")
            time.sleep(1)

            # Verify we're still logged in
            if not self._check_session_valid():
                logger.warning("Keep-alive detected session expiry, attempting refresh...")
                self._refresh_session()
            else:
                self._last_keepalive = time.time()
                logger.info("Keep-alive successful")

        except Exception as e:
            logger.debug(f"Keep-alive error (non-fatal): {e}")

    def _save_debug_html(self, label: str = ""):
        """Save current page source to debug.html for offline analysis.

        Args:
            label: Optional label to include in the file header
        """
        if not self.driver:
            return
        try:
            html = self.driver.page_source
            header = f"<!-- DEBUG DUMP: {label} -->\n<!-- URL: {self.driver.current_url} -->\n<!-- TIME: {datetime.now().isoformat()} -->\n"
            with open(self.DEBUG_HTML_PATH, "w", encoding="utf-8") as f:
                f.write(header + html)
            logger.info(f"Saved debug HTML to {self.DEBUG_HTML_PATH} ({label})")
        except Exception as e:
            logger.error(f"Failed to save debug HTML: {e}")

    def _wait_for_element(self, by: By, value: str, timeout: int = 10):
        """Wait for an element to be present."""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def _wait_for_clickable(self, by: By, value: str, timeout: int = 10):
        """Wait for an element to be clickable."""
        return WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable((by, value))
        )

    def _is_error_page(self) -> bool:
        """Check if the current page is an error page.

        Returns:
            True if on an error page, False otherwise
        """
        try:
            page_source = self.driver.page_source.lower()
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()

            # Check for common error indicators
            error_indicators = [
                "unable to find the page",
                "page not found",
                "404",
                "uh-oh",
                "error occurred",
                "something went wrong",
                "access denied",
                "not authorized",
                "maintenance-logo",  # Learning Suite uses this on error pages
            ]

            for indicator in error_indicators:
                if indicator in page_text or indicator in page_source:
                    logger.warning(f"Error page detected: found '{indicator}'")
                    return True

            return False
        except Exception as e:
            logger.debug(f"Error checking for error page: {e}")
            return False

    def _check_session_valid(self) -> bool:
        """Check if the current session is still valid (logged in).

        Returns:
            True if still logged in, False if session expired
        """
        try:
            current_url = self.driver.current_url

            # If we got redirected to CAS login, session expired
            if "cas.byu.edu" in current_url:
                logger.warning("Session expired - redirected to CAS login")
                return False

            # If we're on a Duo page, need re-auth
            if "duo" in current_url.lower():
                logger.warning("Session expired - Duo authentication required")
                return False

            # If we're on an auth/SAML page
            if any(x in current_url.lower() for x in ["authenticate", "saml", "idp"]):
                logger.warning("Session expired - redirected to auth page")
                return False

            # Check page content for login/session expiry messages
            try:
                page_source = self.driver.page_source.lower()
                for indicator in self.SESSION_EXPIRED_INDICATORS:
                    if indicator in page_source:
                        logger.warning(f"Session expired - detected '{indicator}' in page")
                        return False
            except Exception:
                # If we can't read page source, assume session is still valid
                pass

            return True
        except Exception as e:
            logger.error(f"Error checking session: {e}")
            return False

    def _safe_navigate(self, url: str, description: str = "", retry_on_session_expire: bool = True) -> bool:
        """Safely navigate to a URL and verify the page loaded correctly.

        If session has expired, attempts to refresh the session and retry
        the navigation once.

        Args:
            url: The URL to navigate to
            description: Description for logging
            retry_on_session_expire: If True, attempt session refresh on expiry

        Returns:
            True if navigation successful, False if error page or timeout
        """
        try:
            logger.info(f"Navigating to: {url} ({description})")
            self.driver.get(url)
            time.sleep(2)

            # Check if session is still valid (not redirected to login)
            if not self._check_session_valid():
                if retry_on_session_expire:
                    logger.warning(f"Session expired during navigation to {description}, attempting refresh...")
                    self._save_debug_html(f"session_expired_{description}")
                    if self._refresh_session():
                        # Retry navigation after session refresh (without further retry)
                        return self._safe_navigate(url, description, retry_on_session_expire=False)
                logger.error("Session expired during navigation - could not recover")
                self._save_debug_html(f"session_expired_final_{description}")
                return False

            # Check if we landed on an error page
            if self._is_error_page():
                logger.warning(f"Navigation to {description} resulted in error page")
                self._save_debug_html(f"error_{description}")
                return False

            # Verify we're still on Learning Suite (and not redirected)
            current_url = self.driver.current_url
            if "learningsuite.byu.edu" not in current_url:
                logger.warning(f"Unexpected redirect: {current_url}")
                if retry_on_session_expire:
                    logger.warning("Attempting session refresh after unexpected redirect...")
                    if self._refresh_session():
                        return self._safe_navigate(url, description, retry_on_session_expire=False)
                return False

            # Additional check - make sure we actually navigated to the expected path
            # (some courses might redirect to a different page)
            if "cid-" in url and "cid-" not in current_url:
                logger.warning(f"Course context lost - redirected away from course page")
                return False

            return True
        except TimeoutException:
            logger.warning(f"Timeout navigating to {description}")
            return False
        except Exception as e:
            logger.error(f"Error navigating to {description}: {e}")
            return False

    def _find_element_by_multiple_selectors(self, selectors: list, timeout: int = 10):
        """Try multiple selectors to find an element.

        Args:
            selectors: List of (By, value) tuples to try
            timeout: How long to wait for each selector

        Returns:
            The found element or None
        """
        for by, value in selectors:
            try:
                element = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((by, value))
                )
                logger.info(f"Found element using {by}='{value}'")
                return element
            except TimeoutException:
                continue
        return None

    def check_already_logged_in(self) -> bool:
        """Check if user is already logged into Learning Suite.

        Opens Learning Suite and checks if we're already authenticated
        (URL has session pattern like /.XXXX/student) or if we're
        redirected to CAS login.

        Returns:
            True if already logged in, False if needs authentication
        """
        if not self.driver:
            self._setup_driver()

        logger.info("Checking if already logged in to Learning Suite...")
        logger.info(f"Navigating to {self.LEARNING_SUITE_URL}...")

        # Set page load timeout to prevent hanging
        self.driver.set_page_load_timeout(30)

        try:
            self.driver.get(self.LEARNING_SUITE_URL)
        except TimeoutException:
            logger.error("Page load timed out after 30 seconds")
            return False

        logger.info("Page loaded, waiting for redirect...")
        time.sleep(3)

        current_url = self.driver.current_url
        logger.info(f"Current URL after navigation: {current_url}")

        # Check if we're on CAS login page (not logged in)
        if "cas.byu.edu" in current_url:
            logger.info("Redirected to CAS - not logged in")
            return False

        # Check if we're on a Duo/auth page (not logged in)
        if any(x in current_url.lower() for x in ["duo", "authenticate", "saml", "idp"]):
            logger.info("Redirected to auth page - not logged in")
            return False

        # Check if URL has session pattern (/.XXXX format means logged in)
        if re.match(r'https://learningsuite\.byu\.edu/\.[A-Za-z0-9]+', current_url):
            # Additional check - verify we're not on an error page
            if self._is_error_page():
                logger.warning("Logged in but on error page")
                return False

            # Extract the dynamic base URL for future use
            self.dynamic_base_url = self._extract_dynamic_base_url()
            logger.info(f"Already logged in! Session base: {self.dynamic_base_url}")
            return True

        # Fallback - check if we can see course content
        try:
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            if "sign in" in page_text or "log in" in page_text:
                logger.info("Login prompt detected - not logged in")
                return False
        except Exception as e:
            logger.debug(f"Error checking page content: {e}")

        # If we got here and we're still on Learning Suite, assume logged in
        if "learningsuite.byu.edu" in current_url:
            self.dynamic_base_url = self._extract_dynamic_base_url()
            logger.info("Appears to be logged in (on Learning Suite domain)")
            return True

        logger.info("Unknown state - assuming not logged in")
        return False

    def login(self, netid: str, password: str) -> bool:
        """Log in to BYU Learning Suite via CAS.

        Args:
            netid: BYU NetID
            password: BYU password

        Returns:
            True if login successful, False otherwise
        """
        if not self.driver:
            self._setup_driver()

        logger.info("Navigating to Learning Suite...")
        self.driver.get(self.LEARNING_SUITE_URL)
        time.sleep(3)

        # Log current URL for debugging
        logger.info(f"Current URL: {self.driver.current_url}")

        # Check if we're redirected to CAS login
        if "cas.byu.edu" in self.driver.current_url:
            logger.info("Redirected to CAS login page")

            # Log page source snippet for debugging
            try:
                page_source = self.driver.page_source[:2000]
                logger.info(f"Page source preview: {page_source[:500]}...")
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            try:
                # Try multiple selectors for NetID field
                netid_selectors = [
                    (By.ID, "netid"),
                    (By.ID, "username"),
                    (By.NAME, "netid"),
                    (By.NAME, "username"),
                    (By.CSS_SELECTOR, "input[type='text']"),
                    (By.CSS_SELECTOR, "input#netid"),
                    (By.CSS_SELECTOR, "input#username"),
                    (By.CSS_SELECTOR, "[name='username']"),
                    (By.CSS_SELECTOR, "[name='netid']"),
                ]

                netid_field = self._find_element_by_multiple_selectors(netid_selectors, timeout=5)
                if not netid_field:
                    # Try to find any text input
                    inputs = self.driver.find_elements(By.CSS_SELECTOR, "input")
                    logger.info(f"Found {len(inputs)} input elements")
                    for inp in inputs:
                        inp_type = inp.get_attribute("type")
                        inp_id = inp.get_attribute("id")
                        inp_name = inp.get_attribute("name")
                        logger.info(f"  Input: type={inp_type}, id={inp_id}, name={inp_name}")
                        if inp_type in ["text", "email", None, ""]:
                            netid_field = inp
                            break

                if not netid_field:
                    logger.error("Could not find NetID field")
                    return False

                netid_field.clear()
                netid_field.send_keys(netid)
                logger.info("Entered NetID")

                # Try multiple selectors for password field
                password_selectors = [
                    (By.ID, "password"),
                    (By.NAME, "password"),
                    (By.CSS_SELECTOR, "input[type='password']"),
                    (By.CSS_SELECTOR, "input#password"),
                ]

                password_field = self._find_element_by_multiple_selectors(password_selectors, timeout=5)
                if not password_field:
                    logger.error("Could not find password field")
                    return False

                password_field.clear()
                password_field.send_keys(password)
                logger.info("Entered password")

                # Try multiple selectors for submit button
                submit_selectors = [
                    (By.NAME, "submit"),
                    (By.CSS_SELECTOR, "button[type='submit']"),
                    (By.CSS_SELECTOR, "input[type='submit']"),
                    (By.CSS_SELECTOR, "button.btn-submit"),
                    (By.CSS_SELECTOR, ".btn-primary"),
                    (By.CSS_SELECTOR, "button"),
                    (By.XPATH, "//button[contains(text(),'Sign')]"),
                    (By.XPATH, "//button[contains(text(),'Log')]"),
                    (By.XPATH, "//input[@type='submit']"),
                ]

                submit_button = self._find_element_by_multiple_selectors(submit_selectors, timeout=5)
                if not submit_button:
                    # Try pressing Enter on password field instead
                    password_field.send_keys(Keys.RETURN)
                    logger.info("Pressed Enter to submit")
                else:
                    submit_button.click()
                    logger.info("Clicked submit button")

                # Wait for redirect
                time.sleep(5)
                logger.info(f"After submit URL: {self.driver.current_url}")

                # Check for Duo MFA if present - multiple detection methods
                duo_indicators = [
                    "duosecurity.com" in self.driver.current_url,
                    "duo.com" in self.driver.current_url,
                    "duo-frame" in self.driver.page_source.lower(),
                    "duo_iframe" in self.driver.page_source.lower(),
                    "duosecurity" in self.driver.page_source.lower(),
                ]

                # Also check for BYU's specific auth pages
                byu_auth_indicators = [
                    "authenticate" in self.driver.current_url.lower(),
                    "saml" in self.driver.current_url.lower(),
                    "idp" in self.driver.current_url.lower(),
                ]

                if any(duo_indicators) or any(byu_auth_indicators):
                    logger.info("=" * 50)
                    logger.info("MULTI-FACTOR AUTHENTICATION DETECTED!")
                    logger.info("Please complete authentication in the browser window.")
                    logger.info("You have 2 minutes to complete MFA...")
                    logger.info("=" * 50)
                    print("\n" + "=" * 50)
                    print(">>> WAITING FOR MFA - Complete authentication in browser")
                    print("=" * 50 + "\n")

                    # Wait longer for manual MFA completion
                    try:
                        WebDriverWait(self.driver, 120).until(
                            lambda d: "learningsuite.byu.edu" in d.current_url
                                      and "cas" not in d.current_url.lower()
                                      and "duo" not in d.current_url.lower()
                                      and "authenticate" not in d.current_url.lower()
                        )
                        logger.info("MFA completed successfully")
                    except TimeoutException:
                        logger.error("MFA timeout - took too long")
                        self._save_debug_html("mfa_timeout")
                        return False

                # Verify we're logged in
                time.sleep(2)
                logger.info(f"Final URL: {self.driver.current_url}")

                if "learningsuite.byu.edu" in self.driver.current_url:
                    # Additional verification - check we're not on an error page
                    if self._is_error_page():
                        logger.error("Landed on error page after login")
                        self._save_debug_html("login_error_page")
                        return False

                    # Try to verify we can see course content
                    try:
                        # Wait for the page to have meaningful content
                        WebDriverWait(self.driver, 10).until(
                            lambda d: len(d.find_element(By.TAG_NAME, "body").text) > 100
                        )
                    except TimeoutException:
                        logger.warning("Page content didn't load fully, but proceeding...")

                    # Final verification - try to access the home page
                    home_url = f"{self.LEARNING_SUITE_URL}/"
                    self.driver.get(home_url)
                    time.sleep(2)

                    if self._is_error_page():
                        logger.error("Cannot access Learning Suite home after login")
                        self._save_debug_html("post_login_error")
                        return False

                    # Extract and store the dynamic base URL (includes session segment)
                    self.dynamic_base_url = self._extract_dynamic_base_url()
                    logger.info(f"Session base URL set to: {self.dynamic_base_url}")

                    logger.info("Successfully logged in to Learning Suite")
                    self._save_debug_html("login_success")
                    return True
                else:
                    logger.error(f"Login failed - unexpected URL: {self.driver.current_url}")
                    self._save_debug_html("login_failed")
                    return False

            except TimeoutException:
                logger.error("Login timed out")
                return False
            except Exception as e:
                logger.error(f"Login error: {e}")
                import traceback
                traceback.print_exc()
                return False
        else:
            # Already logged in (session still active)
            self.dynamic_base_url = self._extract_dynamic_base_url()
            logger.info(f"Already logged in to Learning Suite (base: {self.dynamic_base_url})")
            return True

    def get_courses(self) -> list[dict]:
        """Extract list of enrolled courses.

        This method finds course names and CIDs by analyzing DOM proximity on the home page.

        Returns:
            List of course dictionaries with 'name' and 'cid' keys
        """
        courses = []
        print("\n" + "=" * 80)
        print(">>> EXTRACTING COURSE LIST")
        print("=" * 80)

        try:
            time.sleep(3)
            print(f"Current URL: {self.driver.current_url}")

            # DIAGNOSTIC: Print full page text to see what course names are visible
            body_text = self.driver.find_element(By.TAG_NAME, "body").text
            print("\n>>> FULL PAGE TEXT (first 2000 chars):")
            print("-" * 60)
            print(body_text[:2000])
            print("-" * 60)

            # Pattern handles course codes with spaces like "REL C 333", "C S 142", "COM C 301"
            course_pattern = r'([A-Z]{1,5}(?:\s+[A-Z])?\s+\d{3}[A-Z]?\s*\([^)]+\)\s*-\s*[^\n]+)'
            seen_cids = set()

            # Strategy: Find links whose TEXT directly contains a course name
            # This is more reliable than DOM traversal which can match wrong courses
            all_links = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='cid-']")
            print(f"\n>>> Found {len(all_links)} cid links")

            # DIAGNOSTIC: Print all cid links with their text and href
            print("\n>>> ALL CID LINKS FOUND:")
            for i, link in enumerate(all_links[:20]):  # Limit to first 20
                try:
                    href = link.get_attribute("href") or ""
                    link_text = link.text.strip()[:100] if link.text else ""
                    print(f"    [{i}] href='{href}' text='{link_text}'")
                except (NoSuchElementException, StaleElementReferenceException):
                    pass
            print()

            # FIX: Only use links whose TEXT directly contains a course name
            # This avoids the DOM traversal bug where wrong course names get matched
            for link in all_links:
                try:
                    href = link.get_attribute("href")
                    link_text = link.text.strip() if link.text else ""

                    if not href or not link_text:
                        continue

                    # Extract CID from href
                    cid_match = re.search(r'cid-([A-Za-z0-9_-]+)', href)
                    if not cid_match:
                        continue

                    cid = cid_match.group(1)
                    if cid in seen_cids:
                        continue

                    # Check if link text IS a course name (not "Go" or empty)
                    name_match = re.search(course_pattern, link_text)
                    if name_match:
                        course_name = name_match.group(1).strip()
                        # Clean up trailing button words
                        course_name = re.sub(r'\s+(Go|View|Open)\s*$', '', course_name)

                        if re.match(r'^[A-Z]{1,5}(?:\s+[A-Z])?\s+\d{3}', course_name):
                            seen_cids.add(cid)
                            courses.append({
                                "name": course_name,
                                "cid": cid,
                                "url": href
                            })
                            print(f"    [MATCHED] '{course_name}' -> cid-{cid}")

                except Exception as e:
                    logger.debug(f"Error processing link: {e}")
                    continue

            logger.info("=" * 60)
            logger.info(f"TOTAL COURSES FOUND: {len(courses)}")
            for c in courses:
                logger.info(f"  - {c['name']} (cid-{c['cid']})")
            logger.info("=" * 60)

            return courses

        except Exception as e:
            logger.error(f"Error extracting courses: {e}")
            import traceback
            traceback.print_exc()
            return courses

    def _extract_opens_date(self, text: str) -> Optional[str]:
        """Extract a date from 'Opens ...' button text.

        Args:
            text: Button text like "Opens Jan 15" or "Opens Feb 3 at 8:00am"

        Returns:
            ISO format date string or None
        """
        if not text:
            return None

        text_lower = text.lower().strip()
        if not text_lower.startswith("opens"):
            return None

        # Strip the "Opens" prefix
        date_part = re.sub(r'^opens\s+', '', text, flags=re.IGNORECASE).strip()
        if not date_part:
            return None

        # Try parsing the remaining date string
        result = self._parse_ls_date(date_part)
        if result:
            return result
        return self._parse_date(date_part)

    def _map_status(self, button_text: str, status_text: str = "", has_score: bool = False) -> str:
        """Map Learning Suite button/status text to CampusAI status.

        Args:
            button_text: Text from the action button
            status_text: Additional status text if available
            has_score: Whether a score/grade was found for this assignment

        Returns:
            CampusAI status string
        """
        button_lower = button_text.lower().strip()
        status_lower = status_text.lower().strip() if status_text else ""

        # DETAILED STATUS MAPPING LOGGING
        print(f"    [STATUS MAPPING] Input: button='{button_text}', has_score={has_score}")

        # Check for "Opens [date]" pattern - unavailable
        if button_lower.startswith("opens"):
            print(f"    [STATUS MAPPING] -> 'unavailable' (reason: button starts with 'opens')")
            return "unavailable"

        # Check status text for unavailable
        if "unavailable" in status_lower or "unavailable" in button_lower:
            print(f"    [STATUS MAPPING] -> 'unavailable' (reason: contains 'unavailable')")
            return "unavailable"

        # If there's a score/grade, it's likely submitted
        if has_score:
            print(f"    [STATUS MAPPING] -> 'submitted' (reason: has_score=True)")
            return "submitted"

        # Check for ambiguous buttons - these default to not_started
        if button_lower in self.AMBIGUOUS_BUTTONS:
            print(f"    [STATUS MAPPING] -> 'not_started' (reason: ambiguous button '{button_lower}')")
            return "not_started"

        # Look up in mapping - require EXACT match, not substring
        if button_lower in self.STATUS_MAPPING:
            status = self.STATUS_MAPPING[button_lower]
            print(f"    [STATUS MAPPING] -> '{status}' (reason: exact match for '{button_lower}')")
            return status

        # Try partial match for multi-word buttons
        for key, value in self.STATUS_MAPPING.items():
            if key in button_lower:
                print(f"    [STATUS MAPPING] -> '{value}' (reason: partial match on '{key}')")
                return value

        # Default to not_started if unknown
        print(f"    [STATUS MAPPING] -> 'not_started' (reason: unknown button text '{button_text}')")
        return "not_started"

    def _infer_assignment_type(self, title: str, button_text: str) -> str:
        """Infer assignment type from title and button text.

        Args:
            title: Assignment title
            button_text: Action button text

        Returns:
            Assignment type string
        """
        title_lower = title.lower()
        button_lower = button_text.lower()

        if "exam" in title_lower or "exam" in button_lower:
            return "exam"
        elif "quiz" in title_lower:
            return "quiz"
        elif "discussion" in title_lower or "dialog" in title_lower:
            return "discussion"
        elif "reading" in title_lower:
            return "reading"
        elif "submit" in button_lower:
            return "assignment"  # File upload
        else:
            return "assignment"

    def discover_course_tabs(self, course: dict) -> dict:
        """Navigate to course home and discover which tabs exist.

        Args:
            course: Course dictionary with 'cid' and 'name'

        Returns:
            Dictionary mapping tab names to their URLs
        """
        cid = course["cid"]
        course_name = course["name"]
        tabs = {}

        # Navigate to course home page
        course_home_url = f"{self._get_base_url()}/cid-{cid}"

        print(f"\n>>> Discovering tabs for {course_name}...")

        if not self._safe_navigate(course_home_url, f"course home - {course_name}"):
            logger.warning(f"Could not access course home for {course_name}")
            return tabs

        try:
            # Wait for page to fully load
            time.sleep(2)

            # Look for navigation links within the course
            # Learning Suite uses various nav patterns
            nav_selectors = [
                "nav a",
                ".nav a",
                ".navigation a",
                "[class*='nav'] a",
                ".sidebar a",
                ".menu a",
                "a[href*='/student/']",
            ]

            found_links = []
            for selector in nav_selectors:
                try:
                    links = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    found_links.extend(links)
                except (NoSuchElementException, StaleElementReferenceException):
                    continue

            # Also find all links that match course CID pattern
            try:
                cid_links = self.driver.find_elements(By.CSS_SELECTOR, f"a[href*='cid-{cid}']")
                found_links.extend(cid_links)
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            # Extract unique tab URLs
            seen_urls = set()
            for link in found_links:
                try:
                    href = link.get_attribute("href")
                    link_text = link.text.strip().lower()

                    if not href or href in seen_urls:
                        continue

                    seen_urls.add(href)

                    # Identify tab type from URL or text
                    if "gradebook" in href or "grades" in href or "grade" in link_text:
                        tabs["grades"] = href
                    elif "exam" in href or "exam" in link_text:
                        tabs["exams"] = href
                    elif "assignment" in href or "assignment" in link_text:
                        tabs["assignments"] = href
                    elif "content" in href or "content" in link_text or "material" in link_text:
                        tabs["content"] = href
                    elif "schedule" in href or "schedule" in link_text or "calendar" in link_text:
                        tabs["schedule"] = href
                    elif "syllabus" in href or "syllabus" in link_text:
                        tabs["syllabus"] = href

                except Exception as e:
                    continue

            print(f"    Discovered tabs: {list(tabs.keys())}")

        except Exception as e:
            logger.error(f"Error discovering tabs for {course_name}: {e}")

        return tabs

    def scrape_grades_assignments_view(self, course: dict) -> list[dict]:
        """Scrape assignments from the Grades → Assignments view (primary source).

        This view shows ALL gradable items (quizzes, exams, projects, readings, etc.)
        in a grid/table format. Each assignment appears as a column with its name
        in the header.

        Args:
            course: Course dictionary with 'cid' and 'name'

        Returns:
            List of assignment dictionaries
        """
        assignments = []
        cid = course["cid"]
        course_name = course["name"]

        base_url = self._get_base_url()

        # DETAILED LOGGING
        print("\n" + "=" * 70)
        print(f">>> SCRAPING GRADES → ASSIGNMENTS VIEW (PRIMARY SOURCE)")
        print(f">>> COURSE: {course_name}")
        print(f">>> CID: {cid}")
        print("=" * 70)

        # Navigate to course first, then to Grades → Assignments
        course_url = f"{base_url}/cid-{cid}"
        if not self._safe_navigate(course_url, f"course home - {course_name}"):
            print(f">>> WARNING: Could not access course home for {course_name}")
            return assignments

        time.sleep(2)

        # Try to click on Grades link in the sidebar/navigation
        grades_clicked = False
        try:
            # Look for Grades link in various locations
            grades_selectors = [
                "a[href*='gradebook']",
                "a[href*='grades']",
                "//a[contains(text(), 'Grades')]",
                "//a[contains(text(), 'Grade')]",
                ".nav a[href*='grade']",
                "[class*='sidebar'] a[href*='grade']",
            ]

            for selector in grades_selectors:
                try:
                    if selector.startswith("//"):
                        element = self.driver.find_element(By.XPATH, selector)
                    else:
                        element = self.driver.find_element(By.CSS_SELECTOR, selector)

                    if element and element.is_displayed():
                        element.click()
                        grades_clicked = True
                        print(f">>> Clicked Grades link via: {selector}")
                        time.sleep(2)
                        break
                except (NoSuchElementException, StaleElementReferenceException, TimeoutException):
                    continue
        except Exception as e:
            print(f">>> Could not click Grades link: {e}")

        # If clicking didn't work, try direct URL navigation
        if not grades_clicked:
            grades_urls = [
                f"{base_url}/cid-{cid}/student/gradebook",
                f"{base_url}/cid-{cid}/gradebook",
            ]

            for url in grades_urls:
                if self._safe_navigate(url, f"grades page - {course_name}"):
                    grades_clicked = True
                    break

        if not grades_clicked:
            print(f">>> WARNING: Could not access grades for {course_name}")
            return assignments

        time.sleep(2)

        # Now try to click on "Assignments" sub-tab within Grades
        assignments_view_clicked = False
        try:
            assignments_selectors = [
                "a[href*='assignments']",
                "//a[contains(text(), 'Assignments')]",
                "//a[contains(text(), 'Assignment')]",
                "//button[contains(text(), 'Assignments')]",
                "[class*='tab'] a[href*='assignment']",
                ".gradebook-nav a",
            ]

            for selector in assignments_selectors:
                try:
                    if selector.startswith("//"):
                        elements = self.driver.find_elements(By.XPATH, selector)
                    else:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)

                    for element in elements:
                        if element and element.is_displayed():
                            href = element.get_attribute("href") or ""
                            text = element.text.lower()
                            # Make sure we're clicking Assignments, not Summary
                            if "assignment" in href.lower() or "assignment" in text:
                                element.click()
                                assignments_view_clicked = True
                                print(f">>> Clicked Assignments sub-tab")
                                time.sleep(2)
                                break
                    if assignments_view_clicked:
                        break
                except (NoSuchElementException, StaleElementReferenceException, TimeoutException):
                    continue
        except Exception as e:
            print(f">>> Note: Could not click Assignments sub-tab: {e}")

        # Final URL check
        print(f">>> ACTUAL URL: {self.driver.current_url}")

        # SAVE DEBUG HTML
        self._save_debug_html(f"grades_assignments_{course_name}")

        # Now parse the Grades → Assignments grid
        try:
            assignments = self._parse_grades_assignments_grid(course_name, cid)
        except Exception as e:
            print(f">>> ERROR parsing grades grid: {e}")
            import traceback
            traceback.print_exc()

        print(f"\n>>> GRADES → ASSIGNMENTS COMPLETE: {len(assignments)} assignments found")
        print("-" * 70)

        return assignments

    def _parse_grades_assignments_grid(self, course_name: str, cid: str) -> list[dict]:
        """Parse the Grades → Assignments grid view.

        Learning Suite uses a Vue.js frontend where assignment data is embedded
        as JavaScript/JSON in the page source. This method extracts that data.

        Args:
            course_name: Name of the course
            cid: Learning Suite course ID

        Returns:
            List of assignment dictionaries
        """
        assignments = []
        seen_titles = set()

        print(f"\n>>> Parsing Grades → Assignments grid for {course_name} (cid: {cid})")

        # PRIMARY STRATEGY: Extract embedded JavaScript data
        # Learning Suite embeds assignment data as: var assignments = [...];
        page_source = self.driver.page_source

        # Try to extract the assignments JSON from the page source
        js_assignments = self._extract_js_assignments(page_source, course_name, cid)
        if js_assignments:
            print(f">>> Found {len(js_assignments)} assignments via JavaScript extraction")
            for a in js_assignments:
                if a["title"] not in seen_titles:
                    assignments.append(a)
                    seen_titles.add(a["title"])

        # FALLBACK: If no JS data found, try DOM-based parsing
        if len(assignments) == 0:
            print(">>> No JS data found, trying DOM-based parsing...")

            # Try table rows
            tables = self.driver.find_elements(By.TAG_NAME, "table")
            print(f">>> Found {len(tables)} tables on page")

            for table_idx, table in enumerate(tables):
                try:
                    rows = table.find_elements(By.CSS_SELECTOR, "tbody tr, tr")
                    print(f">>> Table {table_idx}: {len(rows)} rows")

                    for row in rows:
                        try:
                            assignment = self._parse_gradebook_row(row, course_name, seen_titles, cid=cid)
                            if assignment:
                                assignments.append(assignment)
                                seen_titles.add(assignment["title"])
                        except StaleElementReferenceException:
                            continue
                        except Exception as e:
                            continue
                except Exception as e:
                    continue

        # Additional fallback strategies
        if len(assignments) == 0:
            print(">>> Trying alternative DOM selectors...")
            item_selectors = [
                "[class*='assignment-item']",
                "[class*='grade-item']",
                ".assignment-row",
                "div[class*='assignment']",
            ]

            for selector in item_selectors:
                try:
                    items = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if items:
                        print(f">>> Found {len(items)} items via selector: {selector}")
                        for item in items:
                            try:
                                assignment = self._parse_gradebook_item(item, course_name, seen_titles, cid=cid)
                                if assignment:
                                    assignments.append(assignment)
                                    seen_titles.add(assignment["title"])
                            except (NoSuchElementException, StaleElementReferenceException, ValueError, TypeError):
                                continue
                except (NoSuchElementException, StaleElementReferenceException):
                    continue

        return assignments

    def _extract_js_assignments(self, page_source: str, course_name: str, cid: str) -> list[dict]:
        """Extract assignments from embedded JavaScript in the page source.

        Learning Suite embeds assignment data as JavaScript variables:
        var assignments = [{...}, {...}, ...];

        Args:
            page_source: HTML page source
            course_name: Name of the course
            cid: Learning Suite course ID

        Returns:
            List of assignment dictionaries
        """
        import json

        assignments = []

        try:
            # Look for the assignments JavaScript variable
            # Pattern: var assignments = [...];
            pattern = r'var\s+assignments\s*=\s*(\[[\s\S]*?\]);'
            match = re.search(pattern, page_source)

            if not match:
                # Try alternative patterns
                pattern = r'assignments\s*:\s*(\[[\s\S]*?\]),'
                match = re.search(pattern, page_source)

            if not match:
                print(">>> No embedded assignments JSON found")
                return assignments

            json_str = match.group(1)

            # Clean up the JSON string (handle JS-style escaping)
            # Replace escaped forward slashes
            json_str = json_str.replace('\\/', '/')

            # Parse the JSON
            try:
                js_data = json.loads(json_str)
            except json.JSONDecodeError as e:
                print(f">>> JSON parse error: {e}")
                # Try fixing common issues
                json_str = re.sub(r',\s*]', ']', json_str)  # Remove trailing commas
                json_str = re.sub(r',\s*}', '}', json_str)
                try:
                    js_data = json.loads(json_str)
                except (json.JSONDecodeError, ValueError):
                    print(">>> Could not parse JSON after cleanup")
                    return assignments

            print(f">>> Parsed {len(js_data)} items from JavaScript")

            # Convert each JS assignment object to our format
            for item in js_data:
                try:
                    assignment = self._convert_js_assignment(item, course_name, cid)
                    if assignment:
                        assignments.append(assignment)
                        print(f"    [JS] '{assignment['title']}' | Due: {assignment['due_date']} | Status: {assignment['status']}")
                except Exception as e:
                    print(f"    [JS ERROR] {e}")
                    continue

        except Exception as e:
            print(f">>> Error extracting JS assignments: {e}")

        return assignments

    def _convert_js_assignment(self, item: dict, course_name: str, cid: str) -> Optional[dict]:
        """Convert a JavaScript assignment object to our format.

        Args:
            item: JavaScript assignment object from Learning Suite
            course_name: Name of the course
            cid: Learning Suite course ID

        Returns:
            Assignment dictionary or None
        """
        try:
            # Extract title (name field in Learning Suite)
            title = item.get("name", "").strip()
            if not title:
                return None

            # Skip certain types or invalid entries
            if len(title) < 2:
                return None

            # Extract due date
            due_date = None
            due_date_str = item.get("dueDate") or item.get("fullDueTime")
            if due_date_str:
                # Handle Learning Suite date format: "2026-01-29 12:30:00" or "Thursday, Jan 29 at 12:30pm"
                due_date = self._parse_ls_date(due_date_str)

            # Determine status based on available fields
            status = "not_started"

            # Check for score/feedback (indicates submitted/graded)
            # Score can be 0 (valid grade) or a number, so check explicitly
            score = item.get("score")
            has_score = score is not None and score != ""

            # Check various indicators that the assignment is submitted/graded
            has_feedback = bool(item.get("feedback"))
            is_graded = item.get("graded", False)
            is_submitted = item.get("submitted", False)
            submission_date = item.get("submissionDate") or item.get("submission_date")

            # Check button text for status hints
            button_text = str(item.get("buttonText", "") or item.get("button", "")).lower()
            if button_text in ("graded", "completed"):
                status = "submitted"
            elif button_text == "view":
                # 'view' is ambiguous — only mark submitted with corroborating evidence
                if has_score or is_graded:
                    status = "submitted"
            elif button_text in ("continue", "resume"):
                status = "in_progress"
            elif button_text in ("unavailable",) or button_text.startswith("opens"):
                status = "unavailable"
                # Extract opens date for unavailable assignments
                if not due_date:
                    opens_date = self._extract_opens_date(str(item.get("buttonText", "") or item.get("button", "")))
                    if opens_date:
                        due_date = opens_date
            elif has_score or is_graded:
                # Only definitive indicators of completion
                status = "submitted"

            print(f"    [JS STATUS] title='{title[:30]}' score={score} feedback={has_feedback} graded={is_graded} submitted={is_submitted} button='{button_text}' -> {status}")

            # Infer assignment type from the 'type' field or title FIRST (needed for URL construction)
            ls_type = item.get("type", "").lower()
            if ls_type == "exam":
                assignment_type = "exam"
            elif ls_type == "quiz":
                assignment_type = "quiz"
            elif "exam" in title.lower():
                assignment_type = "exam"
            elif "quiz" in title.lower():
                assignment_type = "quiz"
            elif "reflection" in title.lower():
                assignment_type = "quiz"  # Reflections use the exam/quiz URL format in Learning Suite
            elif "reading" in title.lower():
                assignment_type = "reading"
            elif "discussion" in title.lower():
                assignment_type = "discussion"
            else:
                assignment_type = "assignment"

            # Build the assignment URL with course ID for proper routing
            # URL format varies by assignment type:
            # - Exams/Quizzes/Reflections: https://learningsuite.byu.edu/cid-{cid}/student/exam/info/id-{id}
            # - Regular assignments: https://learningsuite.byu.edu/cid-{cid}/student/assignment/{id}
            assignment_url = None
            url_suffix = item.get("url")
            assignment_id = item.get("id")

            if assignment_type in ("exam", "quiz"):
                # Exams and quizzes use the exam info URL (no session segment — it expires)
                if assignment_id:
                    assignment_url = f"{self.LEARNING_SUITE_URL}/cid-{cid}/student/exam/info/id-{assignment_id}"
                elif url_suffix:
                    assignment_url = f"{self.LEARNING_SUITE_URL}/cid-{cid}/student/exam/info/id-{url_suffix}"
            else:
                # Regular assignments
                if url_suffix:
                    assignment_url = f"{self.LEARNING_SUITE_URL}/cid-{cid}/student/assignment/{url_suffix}"
                elif assignment_id:
                    assignment_url = f"{self.LEARNING_SUITE_URL}/cid-{cid}/student/assignment/{assignment_id}"

            # Extract and clean description (remove HTML tags and entities)
            description = item.get("description", "")
            description = self._clean_description(description)

            return {
                "title": title,
                "course_name": course_name,
                "due_date": due_date,
                "description": description if description else None,
                "link": assignment_url,
                "status": status,
                "assignment_type": assignment_type,
                "button_text": button_text,
                "ls_cid": cid,
            }

        except Exception as e:
            print(f"    [CONVERT ERROR] {e}")
            return None

    def _parse_ls_date(self, date_str: str) -> Optional[str]:
        """Parse a Learning Suite date string.

        Handles formats like:
        - "2026-01-29 12:30:00"
        - "Thursday, Jan 29 at 12:30pm"
        - "Jan 29 at 12:30pm"

        Args:
            date_str: Date string from Learning Suite

        Returns:
            ISO format date string or None
        """
        if not date_str:
            return None

        mountain = ZoneInfo("America/Denver")

        # Handle SQL-style format: "2026-01-29 12:30:00"
        if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
            try:
                # Try with time
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                dt = dt.replace(tzinfo=mountain)
                return dt.isoformat()
            except ValueError:
                try:
                    # Try date only
                    dt = datetime.strptime(date_str.split()[0], "%Y-%m-%d")
                    dt = dt.replace(tzinfo=mountain)
                    return dt.isoformat()
                except ValueError:
                    pass

        # Handle human-readable format: "Thursday, Jan 29 at 12:30pm"
        # Remove day of week prefix
        date_str = re.sub(r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*', '', date_str, flags=re.IGNORECASE)

        # Normalize whitespace and common variations
        date_str = re.sub(r'\s+', ' ', date_str).strip()
        # "at" is sometimes missing or replaced with comma
        date_str = re.sub(r',\s*(\d{1,2}:\d{2})', r' at \1', date_str)

        # Try parsing
        formats = [
            # With "at" separator
            "%b %d at %I:%M%p",      # "Jan 29 at 12:30pm"
            "%b %d at %I:%M %p",     # "Jan 29 at 12:30 pm"
            "%B %d at %I:%M%p",      # "January 29 at 12:30pm"
            "%B %d at %I:%M %p",     # "January 29 at 12:30 pm"
            "%b %d, %Y at %I:%M%p",  # "Jan 29, 2026 at 12:30pm"
            "%b %d, %Y at %I:%M %p", # "Jan 29, 2026 at 12:30 pm"
            "%B %d, %Y at %I:%M%p",  # "January 29, 2026 at 12:30pm"
            "%B %d, %Y at %I:%M %p", # "January 29, 2026 at 12:30 pm"
            # Without "at" separator
            "%b %d %I:%M%p",         # "Jan 29 12:30pm"
            "%b %d %I:%M %p",        # "Jan 29 12:30 pm"
            "%B %d %I:%M%p",         # "January 29 12:30pm"
            "%B %d %I:%M %p",        # "January 29 12:30 pm"
            # Date only (no time)
            "%b %d, %Y",             # "Jan 29, 2026"
            "%B %d, %Y",             # "January 29, 2026"
            "%b %d",                 # "Jan 29"
            "%B %d",                 # "January 29"
            # With period abbreviation
            "%b. %d at %I:%M%p",     # "Jan. 29 at 12:30pm"
            "%b. %d at %I:%M %p",    # "Jan. 29 at 12:30 pm"
            "%b. %d, %Y at %I:%M%p", # "Jan. 29, 2026 at 12:30pm"
            "%b. %d, %Y",            # "Jan. 29, 2026"
            "%b. %d",                # "Jan. 29"
        ]

        current_year = datetime.now().year

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                # Add year if not present (defaults to 1900)
                if dt.year == 1900:
                    dt = dt.replace(year=current_year)
                # If no time specified, set to 11:59 PM
                if dt.hour == 0 and dt.minute == 0 and "%I" not in fmt and "%H" not in fmt:
                    dt = dt.replace(hour=23, minute=59)
                dt = dt.replace(tzinfo=mountain)
                return dt.isoformat()
            except ValueError:
                continue

        # Fall back to the general date parser
        return self._parse_date(date_str)

    def _parse_gradebook_row(self, row, course_name: str, seen_titles: set, cid: str = None) -> Optional[dict]:
        """Parse a single row from the gradebook table.

        Args:
            row: Selenium element representing the row
            course_name: Name of the course
            seen_titles: Set of already seen titles to avoid duplicates
            cid: Learning Suite course ID for URL construction

        Returns:
            Assignment dictionary or None
        """
        try:
            row_text = row.text.strip()
            if not row_text or len(row_text) < 3:
                return None

            # Skip header rows or category rows
            skip_patterns = [
                'total', 'category', 'weight', 'points possible',
                'average', 'median', 'assignment name', 'due date',
                'grade', 'score', 'status'
            ]
            row_lower = row_text.lower()
            if any(pattern in row_lower and len(row_text) < 50 for pattern in skip_patterns):
                return None

            cells = row.find_elements(By.TAG_NAME, "td")
            if not cells:
                cells = row.find_elements(By.TAG_NAME, "th")

            if not cells:
                return None

            # Extract data from cells
            title = None
            due_date = None
            button_text = ""
            assignment_url = None
            has_score = False
            status = "not_started"

            # Common button/status words to identify
            button_words = {
                'view', 'submit', 'begin', 'continue', 'open', 'completed',
                'unavailable', 'closed', 'resubmit', 'view/submit', 'go',
                'take', 'start', 'resume', 'graded', 'excused'
            }

            for cell in cells:
                cell_text = cell.text.strip()
                cell_lower = cell_text.lower()

                if not cell_text:
                    continue

                # Check for score patterns (85/100, 95%, A, 85 / 100, etc.)
                if re.match(r'^\d+(\.\d+)?\s*/\s*\d+(\.\d+)?%?$', cell_text) or \
                   re.match(r'^\d+(\.\d+)?%?$', cell_text) or \
                   re.match(r'^[A-F][+-]?$', cell_text):
                    has_score = True
                    continue

                # Check for excused/exempt
                if cell_lower in ['excused', 'exempt', 'dropped', 'waived', '--', '-']:
                    has_score = True
                    continue

                # Check for unavailable/opens pattern
                if cell_lower == 'unavailable' or cell_lower.startswith('opens'):
                    button_text = cell_text
                    status = "unavailable"
                    continue

                # Check for button text
                if cell_lower in button_words:
                    button_text = cell_text
                    continue

                # Check for links/buttons inside the cell
                try:
                    link = cell.find_element(By.CSS_SELECTOR, "a, button")
                    link_text = link.text.strip().lower()
                    if link_text in button_words or link_text.startswith('opens'):
                        button_text = link.text.strip()
                        try:
                            assignment_url = link.get_attribute("href")
                        except (StaleElementReferenceException, NoSuchElementException):
                            pass
                        continue
                except NoSuchElementException:
                    pass

                # Check for date patterns
                date_patterns = [
                    r'(\d{1,2}/\d{1,2}/\d{2,4})',  # 1/15/24 or 01/15/2024
                    r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,?\s*\d{4})?)',  # Jan 15 or Jan 15, 2024
                ]
                for pattern in date_patterns:
                    match = re.search(pattern, cell_text, re.IGNORECASE)
                    if match:
                        due_date = self._parse_date(match.group(1))
                        break

                if due_date:
                    continue

                # If we haven't assigned a title yet, this might be it
                if not title and cell_lower not in button_words and len(cell_text) > 2:
                    # Make sure it's not just a number or very short
                    if not re.match(r'^[\d./%]+$', cell_text):
                        title = cell_text
                        # Try to get URL from any link in this cell
                        try:
                            link = cell.find_element(By.TAG_NAME, "a")
                            href = link.get_attribute("href")
                            if href and ("assignment" in href or "exam" in href or "quiz" in href or "cid-" in href):
                                assignment_url = href
                        except (NoSuchElementException, StaleElementReferenceException):
                            pass

            # Validate we have a title
            if not title or title.lower() in button_words or len(title) < 3:
                return None

            # Skip if already seen
            if title in seen_titles:
                return None

            # Determine status
            if has_score:
                status = "submitted"
            elif button_text:
                status = self._map_status(button_text, has_score=has_score)

            # Extract opens date for unavailable assignments
            if status == "unavailable" and not due_date and button_text:
                opens_date = self._extract_opens_date(button_text)
                if opens_date:
                    due_date = opens_date

            # Infer assignment type
            assignment_type = self._infer_assignment_type(title, button_text)

            print(f"    [FOUND] '{title}' | Status: {status} | Due: {due_date}")

            return {
                "title": title,
                "course_name": course_name,
                "due_date": due_date,
                "description": None,
                "link": assignment_url,
                "status": status,
                "assignment_type": assignment_type,
                "button_text": button_text,
                "ls_cid": cid,
            }

        except Exception as e:
            return None

    def _parse_gradebook_item(self, item, course_name: str, seen_titles: set, cid: str = None) -> Optional[dict]:
        """Parse a gradebook item from a div/list-based layout.

        Args:
            item: Selenium element
            course_name: Name of the course
            seen_titles: Set of already seen titles

        Returns:
            Assignment dictionary or None
        """
        try:
            text = item.text.strip()
            if not text or len(text) < 5:
                return None

            # Try to find title from links or headers
            title = None
            assignment_url = None
            due_date = None
            has_score = False
            button_text = ""

            # Look for a link that might be the assignment title
            try:
                links = item.find_elements(By.TAG_NAME, "a")
                for link in links:
                    link_text = link.text.strip()
                    href = link.get_attribute("href") or ""

                    if link_text and len(link_text) > 3:
                        # Check if this looks like a title (not a button)
                        button_words = {'view', 'submit', 'begin', 'continue', 'open'}
                        if link_text.lower() not in button_words:
                            if not title:
                                title = link_text
                                if "assignment" in href or "exam" in href or "cid-" in href:
                                    assignment_url = href
                        else:
                            button_text = link_text
                            if not assignment_url:
                                assignment_url = href
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            # Extract title from text if not found via links
            if not title:
                lines = text.split('\n')
                for line in lines:
                    line = line.strip()
                    if len(line) > 3 and line.lower() not in {'view', 'submit', 'begin', 'continue'}:
                        title = line
                        break

            if not title or title in seen_titles:
                return None

            # Look for date
            date_match = re.search(
                r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,?\s*\d{4})?|\d{1,2}/\d{1,2}/\d{2,4})',
                text, re.IGNORECASE
            )
            if date_match:
                due_date = self._parse_date(date_match.group(1))

            # Look for score
            if re.search(r'\d+(\.\d+)?/\d+|^\d+%$|\b[A-F][+-]?\b', text):
                has_score = True

            status = self._map_status(button_text, has_score=has_score)
            assignment_type = self._infer_assignment_type(title, button_text)

            print(f"    [ITEM] '{title}' | Status: {status}")

            return {
                "title": title,
                "course_name": course_name,
                "due_date": due_date,
                "description": None,
                "link": assignment_url,
                "status": status,
                "assignment_type": assignment_type,
                "button_text": button_text,
                "ls_cid": cid,
            }

        except Exception as e:
            return None

    def _parse_gradebook_columns(self, course_name: str, seen_titles: set) -> list[dict]:
        """Parse assignments from column headers in a gradebook grid.

        In some Learning Suite views, each assignment is a COLUMN with
        the assignment name in the header row.

        Args:
            course_name: Name of the course
            seen_titles: Set of already seen titles

        Returns:
            List of assignment dictionaries
        """
        assignments = []

        try:
            # Look for table headers that might be assignment names
            headers = self.driver.find_elements(By.CSS_SELECTOR, "th, thead td")
            print(f">>> Found {len(headers)} potential column headers")

            for header in headers:
                try:
                    text = header.text.strip()
                    if not text or len(text) < 3:
                        continue

                    # Skip common non-assignment headers
                    skip_words = ['name', 'student', 'total', 'grade', 'score',
                                  'average', 'category', 'weight', 'date']
                    if text.lower() in skip_words:
                        continue

                    if text in seen_titles:
                        continue

                    # This might be an assignment title
                    # Try to find a link for more info
                    assignment_url = None
                    try:
                        link = header.find_element(By.TAG_NAME, "a")
                        assignment_url = link.get_attribute("href")
                    except (NoSuchElementException, StaleElementReferenceException):
                        pass

                    # Infer type from title
                    assignment_type = self._infer_assignment_type(text, "")

                    print(f"    [COLUMN] '{text}'")

                    assignments.append({
                        "title": text,
                        "course_name": course_name,
                        "due_date": None,
                        "description": None,
                        "link": assignment_url,
                        "status": "not_started",
                        "assignment_type": assignment_type,
                        "button_text": "",
                    })
                    seen_titles.add(text)

                except (NoSuchElementException, StaleElementReferenceException, ValueError, TypeError):
                    continue

        except Exception as e:
            print(f">>> Column parsing error: {e}")

        return assignments

    def _parse_assignment_links(self, course_name: str, seen_titles: set) -> list[dict]:
        """Fallback: Find assignments by looking for all relevant links on the page.

        Args:
            course_name: Name of the course
            seen_titles: Set of already seen titles

        Returns:
            List of assignment dictionaries
        """
        assignments = []

        try:
            # Find all links that might be assignments
            all_links = self.driver.find_elements(By.TAG_NAME, "a")
            print(f">>> Scanning {len(all_links)} links for assignments...")

            for link in all_links:
                try:
                    href = link.get_attribute("href") or ""
                    text = link.text.strip()

                    if not text or len(text) < 3:
                        continue

                    # Skip navigation and button links
                    skip_words = {'home', 'grades', 'assignments', 'content', 'syllabus',
                                  'schedule', 'announcements', 'discussions', 'people',
                                  'settings', 'help', 'logout', 'view', 'submit', 'begin'}
                    if text.lower() in skip_words:
                        continue

                    # Check if URL suggests this is an assignment
                    is_assignment_url = any(kw in href.lower() for kw in
                                           ['assignment', 'exam', 'quiz', 'submission', 'homework'])

                    # Check if the text looks like an assignment title
                    looks_like_assignment = (
                        len(text) > 5 and
                        not text.startswith('http') and
                        not re.match(r'^[\d./%]+$', text)
                    )

                    if is_assignment_url and looks_like_assignment:
                        if text not in seen_titles:
                            assignment_type = self._infer_assignment_type(text, "")

                            print(f"    [LINK] '{text}' -> {href[:60]}...")

                            assignments.append({
                                "title": text,
                                "course_name": course_name,
                                "due_date": None,
                                "description": None,
                                "link": href,
                                "status": "not_started",
                                "assignment_type": assignment_type,
                                "button_text": "",
                            })
                            seen_titles.add(text)

                except (NoSuchElementException, StaleElementReferenceException):
                    continue

        except Exception as e:
            print(f">>> Link parsing error: {e}")

        return assignments

    def scrape_grades_tab(self, course: dict) -> list[dict]:
        """Scrape assignments from the Grades tab (legacy method, now calls grades_assignments_view).

        Args:
            course: Course dictionary with 'cid' and 'name'

        Returns:
            List of assignment dictionaries
        """
        # Redirect to the new primary method
        return self.scrape_grades_assignments_view(course)

    def scrape_exams_tab(self, course: dict) -> list[dict]:
        """Scrape assignments from the Exams tab.

        Args:
            course: Course dictionary with 'cid' and 'name'

        Returns:
            List of assignment dictionaries
        """
        assignments = []
        cid = course["cid"]
        course_name = course["name"]

        base_url = self._get_base_url()
        exams_url = f"{base_url}/cid-{cid}/student/exam"

        # DETAILED LOGGING - Course being scraped
        print("\n" + "=" * 70)
        print(f">>> SCRAPING EXAMS TAB")
        print(f">>> COURSE: {course_name}")
        print(f">>> CID: {cid}")
        print(f">>> URL: {exams_url}")
        print("=" * 70)

        # Try multiple URL patterns for exams
        exams_urls = [
            f"{base_url}/cid-{cid}/student/exam",
            f"{base_url}/cid-{cid}/student/exams",
            f"{base_url}/cid-{cid}/student/quizzes",
        ]

        navigated = False
        for url in exams_urls:
            if self._safe_navigate(url, f"exams - {course_name}"):
                navigated = True
                break

        if not navigated:
            print(f">>> WARNING: Could not access exams tab for {course_name}")
            return assignments

        try:
            # SAVE DEBUG HTML before parsing
            self._save_debug_html(f"exams_tab_{course_name}")

            # Find exam rows
            rows = self.driver.find_elements(
                By.CSS_SELECTOR,
                "table tbody tr, .exam-row, .exam-item"
            )

            print(f"\n>>> Found {len(rows)} potential exam rows")

            for i, row in enumerate(rows):
                try:
                    print(f"\n--- Processing exam row {i+1}/{len(rows)} ---")
                    assignment = self._parse_assignment_row(row, course_name, is_exam=True, cid=cid)
                    if assignment:
                        assignments.append(assignment)
                        print(f"    [ADDED] Exam added to list")
                    else:
                        print(f"    [SKIPPED] Row did not yield valid exam")
                except StaleElementReferenceException:
                    print(f"    [ERROR] Stale element - skipping")
                    continue
                except Exception as e:
                    print(f"    [ERROR] Error parsing exam row: {e}")
                    continue

            print(f"\n>>> EXAMS TAB COMPLETE: {len(assignments)} exams found")
            print("-" * 70)

        except TimeoutException:
            print(f">>> WARNING: Exams tab not found or timed out for {course_name}")
        except Exception as e:
            print(f">>> ERROR: Error scraping Exams tab for {course_name}: {e}")

        return assignments

    def scrape_assignments_tab(self, course: dict) -> list[dict]:
        """Scrape assignments from the Assignments tab.

        Args:
            course: Course dictionary with 'cid' and 'name'

        Returns:
            List of assignment dictionaries
        """
        assignments = []
        cid = course["cid"]
        course_name = course["name"]

        base_url = self._get_base_url()
        assignments_url = f"{base_url}/cid-{cid}/student/assignments"

        # DETAILED LOGGING - Course being scraped
        print("\n" + "=" * 70)
        print(f">>> SCRAPING ASSIGNMENTS TAB")
        print(f">>> COURSE: {course_name}")
        print(f">>> CID: {cid}")
        print(f">>> URL: {assignments_url}")
        print("=" * 70)

        # Try multiple URL patterns for assignments
        assignments_urls = [
            f"{base_url}/cid-{cid}/student/assignments",
            f"{base_url}/cid-{cid}/student/homework",
            f"{base_url}/cid-{cid}/student/submissions",
        ]

        navigated = False
        for url in assignments_urls:
            if self._safe_navigate(url, f"assignments - {course_name}"):
                navigated = True
                break

        if not navigated:
            print(f">>> WARNING: Could not access assignments tab for {course_name} - tab may not exist")
            return assignments

        try:
            # DIAGNOSTIC: Print the actual page title/header to verify we're on the right course
            try:
                page_header = self.driver.find_element(By.CSS_SELECTOR, "h1, .course-title, .page-title, header")
                print(f">>> PAGE HEADER TEXT: '{page_header.text[:200]}'")
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            # DIAGNOSTIC: Check current URL to confirm we're on the right course
            print(f">>> ACTUAL URL: {self.driver.current_url}")

            # SAVE DEBUG HTML before parsing
            self._save_debug_html(f"assignments_tab_{course_name}")

            # Find assignment rows - try multiple selectors
            rows = self.driver.find_elements(
                By.CSS_SELECTOR,
                "table tbody tr, .assignment-row, .assignment-item, [class*='assignment']"
            )

            if not rows:
                # Try alternative selectors for list-style layouts
                rows = self.driver.find_elements(By.CSS_SELECTOR, ".list-item, .item-row, li[class*='assign']")

            print(f"\n>>> Found {len(rows)} potential assignment rows")

            for i, row in enumerate(rows):
                try:
                    print(f"\n--- Processing assignment row {i+1}/{len(rows)} ---")
                    assignment = self._parse_assignment_row(row, course_name, is_exam=False, cid=cid)
                    if assignment:
                        assignments.append(assignment)
                        print(f"    [ADDED] Assignment added to list")
                    else:
                        print(f"    [SKIPPED] Row did not yield valid assignment")
                except StaleElementReferenceException:
                    print(f"    [ERROR] Stale element - skipping")
                    continue
                except Exception as e:
                    print(f"    [ERROR] Error parsing assignment row: {e}")
                    continue

            print(f"\n>>> ASSIGNMENTS TAB COMPLETE: {len(assignments)} assignments found")
            print("-" * 70)

        except TimeoutException:
            print(f">>> WARNING: Assignments tab not found or timed out for {course_name}")
        except Exception as e:
            print(f">>> ERROR: Error scraping Assignments tab for {course_name}: {e}")

        return assignments

    def scrape_content_tab(self, course: dict) -> list[dict]:
        """Scrape assignments from the Content tab (modules/schedule view).

        Args:
            course: Course dictionary with 'cid' and 'name'

        Returns:
            List of assignment dictionaries
        """
        assignments = []
        cid = course["cid"]
        course_name = course["name"]

        base_url = self._get_base_url()
        content_url = f"{base_url}/cid-{cid}/student/content"

        # DETAILED LOGGING
        print("\n" + "=" * 70)
        print(f">>> SCRAPING CONTENT TAB")
        print(f">>> COURSE: {course_name}")
        print(f">>> CID: {cid}")
        print(f">>> URL: {content_url}")
        print("=" * 70)

        # Try multiple URL patterns for content
        content_urls = [
            f"{base_url}/cid-{cid}/student/content",
            f"{base_url}/cid-{cid}/student/modules",
            f"{base_url}/cid-{cid}/student/materials",
        ]

        navigated = False
        for url in content_urls:
            if self._safe_navigate(url, f"content - {course_name}"):
                navigated = True
                break

        if not navigated:
            print(f">>> WARNING: Could not access content tab for {course_name} - tab may not exist")
            return assignments

        try:
            print(f">>> ACTUAL URL: {self.driver.current_url}")

            # SAVE DEBUG HTML before parsing
            self._save_debug_html(f"content_tab_{course_name}")

            # Look for assignment links in the content/modules
            # Content pages typically have links to assignments, quizzes, etc.
            assignment_links = self.driver.find_elements(
                By.CSS_SELECTOR,
                "a[href*='assignment'], a[href*='quiz'], a[href*='exam'], a[href*='submit']"
            )

            print(f"\n>>> Found {len(assignment_links)} potential assignment links in content")

            seen_titles = set()
            for link in assignment_links:
                try:
                    title = link.text.strip()
                    href = link.get_attribute("href")

                    if not title or len(title) < 3:
                        continue

                    # Skip duplicates
                    if title in seen_titles:
                        continue
                    seen_titles.add(title)

                    # Try to find due date near the link
                    due_date = None
                    try:
                        parent = link.find_element(By.XPATH, "./..")
                        parent_text = parent.text
                        date_match = re.search(
                            r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,?\s+\d{4})?(?:\s+\d+:\d+\s*[AP]M)?)',
                            parent_text, re.IGNORECASE
                        )
                        if date_match:
                            due_date = self._parse_date(date_match.group(1))
                    except (NoSuchElementException, StaleElementReferenceException, ValueError, TypeError):
                        pass

                    assignment_type = self._infer_assignment_type(title, "")

                    print(f"    [CONTENT] Found: '{title}' -> {href}")

                    assignments.append({
                        "title": title,
                        "course_name": course_name,
                        "due_date": due_date,
                        "description": None,
                        "link": href,
                        "status": "not_started",
                        "assignment_type": assignment_type,
                        "button_text": "",
                    })

                except Exception as e:
                    print(f"    [ERROR] Error processing content link: {e}")
                    continue

            print(f"\n>>> CONTENT TAB COMPLETE: {len(assignments)} assignments found")
            print("-" * 70)

        except TimeoutException:
            print(f">>> WARNING: Content tab not found or timed out for {course_name}")
        except Exception as e:
            print(f">>> ERROR: Error scraping Content tab for {course_name}: {e}")

        return assignments

    def scrape_schedule_tab(self, course: dict) -> list[dict]:
        """Scrape assignments from the Schedule tab (calendar view).

        Args:
            course: Course dictionary with 'cid' and 'name'

        Returns:
            List of assignment dictionaries
        """
        assignments = []
        cid = course["cid"]
        course_name = course["name"]

        base_url = self._get_base_url()
        schedule_url = f"{base_url}/cid-{cid}/student/schedule"

        # DETAILED LOGGING
        print("\n" + "=" * 70)
        print(f">>> SCRAPING SCHEDULE TAB")
        print(f">>> COURSE: {course_name}")
        print(f">>> CID: {cid}")
        print(f">>> URL: {schedule_url}")
        print("=" * 70)

        # Try multiple URL patterns for schedule
        schedule_urls = [
            f"{base_url}/cid-{cid}/student/schedule",
            f"{base_url}/cid-{cid}/student/calendar",
            f"{base_url}/cid-{cid}/student/syllabus",
        ]

        navigated = False
        for url in schedule_urls:
            if self._safe_navigate(url, f"schedule - {course_name}"):
                navigated = True
                break

        if not navigated:
            print(f">>> WARNING: Could not access schedule tab for {course_name} - tab may not exist")
            return assignments

        try:
            print(f">>> ACTUAL URL: {self.driver.current_url}")

            # SAVE DEBUG HTML before parsing
            self._save_debug_html(f"schedule_tab_{course_name}")

            # Schedule pages typically show items by date with title, type, and due info
            # Look for schedule items, rows, or list elements
            rows = self.driver.find_elements(
                By.CSS_SELECTOR,
                "table tbody tr, .schedule-item, .schedule-row, [class*='schedule'], .item-row"
            )

            print(f"\n>>> Found {len(rows)} potential schedule rows")

            for i, row in enumerate(rows):
                try:
                    print(f"\n--- Processing schedule row {i+1}/{len(rows)} ---")
                    assignment = self._parse_assignment_row(row, course_name, is_exam=False, cid=cid)
                    if assignment:
                        assignments.append(assignment)
                        print(f"    [ADDED] Schedule item added to list")
                    else:
                        print(f"    [SKIPPED] Row did not yield valid assignment")
                except StaleElementReferenceException:
                    print(f"    [ERROR] Stale element - skipping")
                    continue
                except Exception as e:
                    print(f"    [ERROR] Error parsing schedule row: {e}")
                    continue

            print(f"\n>>> SCHEDULE TAB COMPLETE: {len(assignments)} assignments found")
            print("-" * 70)

        except TimeoutException:
            print(f">>> WARNING: Schedule tab not found or timed out for {course_name}")
        except Exception as e:
            print(f">>> ERROR: Error scraping Schedule tab for {course_name}: {e}")

        return assignments

    def _parse_assignment_row(self, row, course_name: str, is_exam: bool = False, cid: str = None) -> Optional[dict]:
        """Parse a single assignment row.

        Args:
            row: Selenium element representing the row
            course_name: Name of the course
            is_exam: Whether this is from the Exams tab

        Returns:
            Assignment dictionary or None if parsing fails
        """
        try:
            # Get all text content
            row_text = row.text.strip()
            if not row_text:
                print(f"    [EMPTY] Row has no text content")
                return None

            # Button words to exclude from titles
            button_words = {'view', 'submit', 'begin', 'continue', 'open', 'completed',
                           'unavailable', 'closed', 'resubmit', 'view/submit', 'go',
                           'take', 'start', 'resume', 'graded'}

            # Try to parse as a table row first (most common in Learning Suite)
            cells = row.find_elements(By.TAG_NAME, "td")
            title = None
            button_text = ""
            assignment_url = None
            due_date = None
            has_score = False
            is_unavailable = False  # Flag to track unavailable status - once set, don't overwrite

            # DETAILED LOGGING - Show raw row text
            print(f"    [RAW TEXT] {row_text[:150]}{'...' if len(row_text) > 150 else ''}")

            if cells:
                # Table row - look through cells
                print(f"    [TABLE ROW] Found {len(cells)} cells")

                for i, cell in enumerate(cells):
                    cell_text = cell.text.strip()
                    cell_html = ""
                    try:
                        cell_html = cell.get_attribute("innerHTML")[:200] if cell.get_attribute("innerHTML") else ""
                    except (StaleElementReferenceException, NoSuchElementException):
                        pass

                    # DIAGNOSTIC: Print ALL cells including empty ones to see structure
                    print(f"      Cell[{i}]: text='{cell_text[:80]}{'...' if len(cell_text) > 80 else ''}'")
                    if cell_html:
                        print(f"               html='{cell_html[:100]}{'...' if len(cell_html) > 100 else ''}'")

                    if not cell_text:
                        continue

                    cell_lower = cell_text.lower()

                    # PRIORITY CHECK: Check for "unavailable" FIRST before looking for buttons
                    # Once unavailable is found, it should NOT be overwritten by subsequent button checks
                    if cell_lower == 'unavailable' or cell_lower.startswith('opens'):
                        button_text = cell_text
                        is_unavailable = True
                        print(f"        -> UNAVAILABLE STATUS FOUND: '{button_text}' (locked, won't be overwritten)")
                        continue

                    # Check for EXCUSED or other grade text (before button check)
                    if cell_lower in ['excused', 'exempt', 'dropped', 'waived']:
                        has_score = True  # Treat as submitted/graded
                        print(f"        -> EXCUSED/EXEMPT FOUND: '{cell_text}' (treating as submitted)")
                        continue

                    # Check if this cell contains a button/link (but only if not already unavailable)
                    if not is_unavailable:
                        try:
                            button_or_link = cell.find_element(By.CSS_SELECTOR, "a, button")
                            btn_text = button_or_link.text.strip().lower()
                            if btn_text in button_words or btn_text.startswith('opens'):
                                button_text = button_or_link.text.strip()
                                print(f"        -> BUTTON FOUND: '{button_text}'")
                                try:
                                    assignment_url = button_or_link.get_attribute("href")
                                except (StaleElementReferenceException, NoSuchElementException):
                                    pass
                                continue
                        except NoSuchElementException:
                            pass

                    # Check if this cell is just a button word (but only if not already unavailable)
                    if cell_lower in button_words or cell_lower.startswith('opens'):
                        if not button_text and not is_unavailable:  # Only set if not already found
                            button_text = cell_text
                            print(f"        -> BUTTON TEXT (cell): '{button_text}'")
                        continue

                    # Check for score/grade pattern (e.g., "85/100", "95%", "A", "Excused")
                    if re.match(r'^\d+(\.\d+)?(/\d+)?%?$', cell_text) or re.match(r'^[A-F][+-]?$', cell_text):
                        has_score = True
                        print(f"        -> SCORE FOUND: '{cell_text}'")
                        continue

                    # ENHANCED DATE DETECTION - Check multiple patterns
                    # Pattern 1: MM/DD format
                    if re.match(r'^\d{1,2}/\d{1,2}', cell_text):
                        date_match = re.search(
                            r'(\d{1,2}/\d{1,2}/\d{2,4}(?:\s+\d+:\d+\s*[AP]M)?)',
                            cell_text
                        )
                        if date_match:
                            due_date = self._parse_date(date_match.group(1))
                            print(f"        -> DATE FOUND (MM/DD): '{cell_text}' -> parsed: {due_date}")
                        continue

                    # Pattern 2: Month name format (Jan 15, 2024)
                    month_pattern = r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}'
                    if re.search(month_pattern, cell_text, re.IGNORECASE):
                        print(f"        -> DATE FOUND (Month name): '{cell_text}'")
                        due_date = self._parse_date(cell_text)
                        if due_date:
                            print(f"           -> Parsed to: {due_date}")
                        else:
                            print(f"           -> FAILED TO PARSE!")
                        continue

                    # Otherwise, this is likely the title
                    if not title and cell_lower not in button_words:
                        title = cell_text
                        print(f"        -> TITLE FOUND: '{title}'")

                # FALLBACK: If no assignment URL was found yet, search all links in the row
                if not assignment_url:
                    try:
                        all_links = row.find_elements(By.TAG_NAME, "a")
                        for link in all_links:
                            href = link.get_attribute("href")
                            if href:
                                # Accept any Learning Suite link or common assignment patterns
                                if ("learningsuite" in href or
                                    "exam" in href or
                                    "assignment" in href or
                                    "quiz" in href or
                                    "submit" in href or
                                    "cid-" in href):
                                    assignment_url = href
                                    print(f"    [FALLBACK LINK] Found: {href}")
                                    break
                    except (NoSuchElementException, StaleElementReferenceException):
                        pass

            else:
                # Not a table row - parse from text
                print(f"    [NON-TABLE] Parsing from text...")
                text_parts = [p.strip() for p in row_text.split('\n') if p.strip()]

                for part in text_parts:
                    part_lower = part.lower()
                    print(f"      Part: '{part}'")

                    # PRIORITY CHECK: Check for "unavailable" FIRST
                    if part_lower == 'unavailable' or part_lower.startswith('opens'):
                        button_text = part
                        is_unavailable = True
                        print(f"        -> UNAVAILABLE STATUS FOUND: '{button_text}' (locked)")
                        continue

                    # Check if it's a button word (but only if not already unavailable)
                    if part_lower in button_words:
                        if not is_unavailable:
                            button_text = part
                            print(f"        -> BUTTON TEXT: '{button_text}'")
                    elif not title and part_lower not in button_words:
                        # Skip if it looks like a date
                        if not re.match(r'^\d{1,2}/\d{1,2}', part):
                            title = part
                            print(f"        -> TITLE: '{title}'")

                # Look for dates in full text
                date_match = re.search(
                    r'(\d{1,2}/\d{1,2}/\d{2,4}(?:\s+\d+:\d+\s*[AP]M)?)',
                    row_text
                )
                if date_match:
                    due_date = self._parse_date(date_match.group(1))

                # Try to find link - be more permissive about URL patterns
                try:
                    links = row.find_elements(By.TAG_NAME, "a")
                    for link in links:
                        href = link.get_attribute("href")
                        if href:
                            # Accept any Learning Suite link, or links with common assignment patterns
                            if ("learningsuite" in href or
                                "exam" in href or
                                "assignment" in href or
                                "quiz" in href or
                                "submit" in href or
                                "cid-" in href):
                                assignment_url = href
                                break
                except (NoSuchElementException, StaleElementReferenceException):
                    pass

            # Validate title - skip if it's empty or just a button word
            if not title or title.lower() in button_words:
                print(f"    [SKIP] No valid title found")
                return None

            # If title is too short or generic, skip
            if len(title) < 3:
                print(f"    [SKIP] Title too short: '{title}'")
                return None

            # Map status - pass has_score for better determination
            status = self._map_status(button_text, has_score=has_score)

            # Infer assignment type
            assignment_type = "exam" if is_exam else self._infer_assignment_type(title, button_text)

            # DETAILED LOGGING - Final assignment details
            print(f"\n    ========== ASSIGNMENT PARSED ==========")
            print(f"    TITLE:       '{title}'")
            print(f"    COURSE:      '{course_name}'")
            print(f"    BUTTON:      '{button_text}'")
            print(f"    STATUS:      '{status}'")
            print(f"    HAS SCORE:   {has_score}")
            print(f"    DUE DATE:    {due_date}")
            print(f"    TYPE:        {assignment_type}")
            print(f"    ===========================================\n")

            return {
                "title": title,
                "course_name": course_name,
                "due_date": due_date,
                "description": None,
                "link": assignment_url,
                "status": status,
                "assignment_type": assignment_type,
                "button_text": button_text,
                "ls_cid": cid,
            }

        except Exception as e:
            print(f"    [ERROR] Error parsing assignment row: {e}")
            return None

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse a date string into ISO format.

        Args:
            date_str: Date string in various formats

        Returns:
            ISO format date string or None
        """
        original_str = date_str
        date_str = date_str.strip()
        mountain = ZoneInfo("America/Denver")

        # Strip timezone suffixes (MST, EST, PST, MDT, etc.)
        date_str = re.sub(r'\s+(MST|EST|PST|CST|MDT|EDT|PDT|CDT|UTC|GMT)$', '', date_str, flags=re.IGNORECASE)

        # Get current year for dates without year
        current_year = datetime.now().year

        # Normalize whitespace
        date_str = re.sub(r'\s+', ' ', date_str).strip()
        # Remove "Due:" or "Due " prefix
        date_str = re.sub(r'^Due:?\s*', '', date_str, flags=re.IGNORECASE).strip()
        # Remove day of week prefix (in case _parse_date called directly)
        date_str = re.sub(r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*', '', date_str, flags=re.IGNORECASE)

        # Expanded date formats - trying more variations
        date_formats = [
            # Learning Suite format WITHOUT year: "Jan 11 11:59 pm"
            "%b %d %I:%M %p",
            "%b %d %I:%M%p",  # No space before AM/PM
            "%B %d %I:%M %p",
            "%B %d %I:%M%p",

            # With "at" separator, no year
            "%b %d at %I:%M %p",
            "%b %d at %I:%M%p",
            "%B %d at %I:%M %p",
            "%B %d at %I:%M%p",

            # Full month name formats WITH year
            "%B %d, %Y at %I:%M %p",
            "%B %d, %Y at %I:%M%p",
            "%B %d, %Y %I:%M %p",
            "%B %d, %Y %I:%M%p",
            "%B %d %Y at %I:%M %p",
            "%B %d %Y %I:%M %p",
            "%B %d, %Y",
            "%B %d %Y",

            # Abbreviated month name formats WITH year
            "%b %d, %Y at %I:%M %p",
            "%b %d, %Y at %I:%M%p",
            "%b %d, %Y %I:%M %p",
            "%b %d, %Y %I:%M%p",
            "%b %d %Y at %I:%M %p",
            "%b %d %Y %I:%M %p",
            "%b %d, %Y",
            "%b %d %Y",

            # With period abbreviation (Jan. 15)
            "%b. %d, %Y at %I:%M %p",
            "%b. %d, %Y at %I:%M%p",
            "%b. %d, %Y %I:%M %p",
            "%b. %d, %Y",
            "%b. %d %Y",
            "%b. %d at %I:%M %p",
            "%b. %d at %I:%M%p",
            "%b. %d %I:%M %p",
            "%b. %d %I:%M%p",
            "%b. %d",

            # Date only (no year, no time)
            "%b %d",
            "%B %d",

            # Numeric formats
            "%m/%d/%Y %I:%M %p",
            "%m/%d/%Y %I:%M%p",
            "%m/%d/%Y",
            "%m/%d/%y %I:%M %p",
            "%m/%d/%y %I:%M%p",
            "%m/%d/%y",

            # ISO-like formats
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
        ]

        # Try each format
        for fmt in date_formats:
            try:
                dt = datetime.strptime(date_str, fmt)

                # If parsed without year (year defaults to 1900), add current year
                if dt.year == 1900:
                    dt = dt.replace(year=current_year)

                # If no time specified, set to 11:59 PM
                if dt.hour == 0 and dt.minute == 0 and "%I" not in fmt and "%H" not in fmt:
                    dt = dt.replace(hour=23, minute=59)

                dt = dt.replace(tzinfo=mountain)
                print(f"           [DATE PARSE SUCCESS] '{original_str}' -> {dt.isoformat()} (format: {fmt})")
                return dt.isoformat()
            except ValueError:
                continue

        # Try extracting just the date part if it has extra text
        # e.g., "Due: Jan 15, 2024" or "Jan 15, 2024 11:59 PM EST"
        date_only_patterns = [
            r'(\w+\s+\d{1,2},?\s+\d{4})',  # Month DD, YYYY
            r'(\d{1,2}/\d{1,2}/\d{2,4})',   # M/D/Y
        ]

        for pattern in date_only_patterns:
            match = re.search(pattern, date_str)
            if match:
                extracted = match.group(1)
                if extracted != date_str:  # Only if we actually extracted something different
                    print(f"           [DATE EXTRACT] Trying extracted: '{extracted}'")
                    result = self._parse_date(extracted)  # Recursive call
                    if result:
                        return result

        print(f"           [DATE PARSE FAILED] Could not parse: '{original_str}'")
        return None

    def scrape_all_courses(self, progress_callback=None, save_per_course=False) -> list[dict]:
        """Scrape assignments from all enrolled courses.

        Primary strategy: Use Grades -> Assignments view which contains ALL
        gradable items (quizzes, exams, projects, readings, etc.)

        Includes session resilience:
        - Keep-alive requests between courses to prevent session timeout
        - Session validity checks before each course
        - Automatic session refresh/retry on failure
        - Tracks remaining courses so a failed course can be retried

        Args:
            progress_callback: Optional callable(current_index, total_courses, course_name)
                called after each course is scraped for progress reporting.
            save_per_course: If True, call update_database() after each course
                so assignments appear incrementally in the frontend.

        Returns:
            List of all assignments across all courses
        """
        all_assignments = []
        courses = self.get_courses()

        if not courses:
            logger.warning("No courses found to scrape")
            return all_assignments

        total_courses = len(courses)
        if progress_callback:
            progress_callback(0, total_courses, "Starting...")

        # Track totals per course for summary
        course_totals = {}
        # Track per-course DB results when save_per_course is enabled
        self._per_course_db_results = []
        # Track failed courses for potential retry
        failed_courses = []

        for i, course in enumerate(courses):
            course_assignments = []
            existing_titles = set()

            print(f"\n{'#' * 70}")
            print(f"### PROCESSING COURSE: {course['name']} ({i+1}/{total_courses})")
            print(f"{'#' * 70}")

            # SESSION CHECK: Before each course, verify session is still valid
            if not self._check_session_valid():
                logger.warning(f"Session invalid before scraping {course['name']}, attempting refresh...")
                if not self._refresh_session():
                    logger.error(f"Session refresh failed before {course['name']}, adding to retry queue")
                    failed_courses.append((i, course))
                    if progress_callback:
                        progress_callback(i + 1, total_courses, f"{course['name']} (session error)")
                    continue

            # KEEP-ALIVE: Touch the base URL periodically to refresh session timer
            # Do this every 2 courses to stay well within session timeout
            if i > 0 and i % 2 == 0:
                self._keepalive()

            # PRIMARY SOURCE: Grades -> Assignments view
            # This should contain ALL gradable items including quizzes, exams, projects, etc.
            grades_assignments = []
            try:
                grades_assignments = self.scrape_grades_assignments_view(course)
                for a in grades_assignments:
                    course_assignments.append(a)
                    existing_titles.add(a["title"])
            except Exception as e:
                logger.error(f"Error scraping grades view for {course['name']}: {e}")
                # Check if this was a session error
                if not self._check_session_valid():
                    logger.warning(f"Session expired during {course['name']}, attempting refresh...")
                    if self._refresh_session():
                        # Retry this course after session refresh
                        try:
                            grades_assignments = self.scrape_grades_assignments_view(course)
                            for a in grades_assignments:
                                course_assignments.append(a)
                                existing_titles.add(a["title"])
                        except Exception as retry_e:
                            logger.error(f"Retry failed for {course['name']}: {retry_e}")
                            failed_courses.append((i, course))
                    else:
                        failed_courses.append((i, course))
                        if progress_callback:
                            progress_callback(i + 1, total_courses, f"{course['name']} (failed)")
                        continue

            time.sleep(1)

            # SECONDARY: If Grades view returned very few items, also try Exams tab
            # This catches cases where exams are listed separately
            if len(grades_assignments) < 5:
                print(f">>> Grades view found only {len(grades_assignments)} items, checking Exams tab...")
                try:
                    exams_assignments = self.scrape_exams_tab(course)
                    for exam in exams_assignments:
                        if exam["title"] not in existing_titles:
                            course_assignments.append(exam)
                            existing_titles.add(exam["title"])
                            print(f"    [NEW FROM EXAMS] {exam['title']}")
                except Exception as e:
                    logger.error(f"Error scraping exams tab for {course['name']}: {e}")

                time.sleep(1)

            # Track course total
            course_totals[course['name']] = len(course_assignments)

            print(f"\n>>> COURSE COMPLETE: {course['name']}")
            print(f">>> Total assignments found: {len(course_assignments)}")

            # Save this course's assignments to DB immediately if requested
            if save_per_course and course_assignments:
                db_result = self.update_database(course_assignments)
                self._per_course_db_results.append(db_result)

            all_assignments.extend(course_assignments)

            # Report progress after each course
            if progress_callback:
                progress_callback(i + 1, total_courses, course['name'])

        # RETRY FAILED COURSES: If any courses failed due to session issues, retry them
        if failed_courses:
            logger.info(f"Retrying {len(failed_courses)} failed courses...")
            print(f"\n{'=' * 70}")
            print(f"RETRYING {len(failed_courses)} FAILED COURSES")
            print(f"{'=' * 70}")

            # First, try to refresh the session
            if self._check_session_valid() or self._refresh_session():
                for original_idx, course in failed_courses:
                    print(f"\n### RETRY: {course['name']}")
                    course_assignments = []
                    existing_titles = set()

                    if not self._check_session_valid():
                        logger.error(f"Session still invalid, skipping retry for {course['name']}")
                        continue

                    try:
                        grades_assignments = self.scrape_grades_assignments_view(course)
                        for a in grades_assignments:
                            course_assignments.append(a)
                            existing_titles.add(a["title"])

                        if len(grades_assignments) < 5:
                            try:
                                exams_assignments = self.scrape_exams_tab(course)
                                for exam in exams_assignments:
                                    if exam["title"] not in existing_titles:
                                        course_assignments.append(exam)
                                        existing_titles.add(exam["title"])
                            except Exception:
                                pass

                        course_totals[course['name']] = len(course_assignments)
                        print(f">>> RETRY COMPLETE: {course['name']} - {len(course_assignments)} assignments")

                        if save_per_course and course_assignments:
                            db_result = self.update_database(course_assignments)
                            self._per_course_db_results.append(db_result)

                        all_assignments.extend(course_assignments)

                    except Exception as e:
                        logger.error(f"Retry failed for {course['name']}: {e}")
                        course_totals[course['name']] = 0

                    time.sleep(1)
            else:
                logger.error("Cannot refresh session for retry, skipping failed courses")
                for _, course in failed_courses:
                    course_totals[course['name']] = 0

        # Print final summary with totals per course
        print("\n" + "=" * 70)
        print("SCRAPING SUMMARY - ASSIGNMENTS PER COURSE")
        print("=" * 70)
        for course_name, count in course_totals.items():
            print(f"  {course_name}: {count} assignments")
        if failed_courses:
            print(f"\n  COURSES THAT FAILED: {len(failed_courses)}")
            for _, course in failed_courses:
                final_count = course_totals.get(course['name'], 0)
                status = f"{final_count} assignments (recovered)" if final_count > 0 else "FAILED"
                print(f"    - {course['name']}: {status}")
        print("-" * 70)
        print(f"  TOTAL: {len(all_assignments)} assignments")
        print("=" * 70)

        logger.info(f"Total assignments scraped: {len(all_assignments)}")
        return all_assignments

    def update_database(self, assignments: list[dict]) -> dict:
        """Update database with scraped assignments using change detection.

        Args:
            assignments: List of assignment dictionaries

        Returns:
            Summary dictionary with counts
        """
        if not self.supabase:
            print("\n[DB ERROR] Supabase client not initialized")
            return {"error": "Database not connected"}

        summary = {"new": 0, "modified": 0, "unchanged": 0, "errors": 0}
        now = datetime.now(timezone.utc).isoformat()

        print("\n" + "=" * 70)
        print(">>> UPDATING DATABASE")
        print(f">>> Total assignments to process: {len(assignments)}")
        print("=" * 70)

        for i, assignment in enumerate(assignments):
            try:
                # Sanitize URL to remove session segment (prevents error pages)
                raw_link = assignment.get("link")
                cid = assignment.get("ls_cid")
                sanitized_link = self._sanitize_url(raw_link, cid=cid) if raw_link else None
                assignment["link"] = sanitized_link

                # Clean description (remove HTML tags and entities)
                raw_desc = assignment.get("description")
                if raw_desc:
                    assignment["description"] = self._clean_description(raw_desc)

                # Clean title (remove HTML entities like &amp;)
                raw_title = assignment.get("title", "")
                assignment["title"] = html.unescape(raw_title)

                print(f"\n--- DB Update {i+1}/{len(assignments)} ---")
                print(f"    Title: '{assignment['title']}'")
                print(f"    Course: '{assignment['course_name']}'")
                print(f"    Status: '{assignment.get('status')}'")
                if raw_link != sanitized_link:
                    print(f"    Link (sanitized): {sanitized_link}")

                # Check if assignment exists (match by title + course_name)
                existing = self.supabase.table("assignments").select("*").eq(
                    "title", assignment["title"]
                ).eq(
                    "course_name", assignment["course_name"]
                ).execute()

                if existing.data:
                    # Update existing assignment
                    existing_record = existing.data[0]
                    is_modified = False

                    # Check for changes in key fields
                    if existing_record.get("due_date") != assignment.get("due_date"):
                        is_modified = True
                    if existing_record.get("description") != assignment.get("description"):
                        is_modified = True

                    update_data = {
                        "last_scraped_at": now,
                        "is_modified": is_modified,
                        "link": assignment.get("link"),
                        "learning_suite_url": assignment.get("link"),
                        "assignment_type": assignment.get("assignment_type"),
                        "ls_cid": assignment.get("ls_cid"),
                    }

                    # Only update status if Learning Suite shows a definitive change
                    # (e.g., submitted when it was previously not_started)
                    ls_status = assignment.get("status")
                    current_status = existing_record.get("status")

                    # Update status only for these transitions:
                    # - anything -> submitted (user completed it)
                    # - unavailable -> not_started (became available)
                    # - newly_assigned stays unless LS shows definitive state
                    if ls_status == "submitted" and current_status != "submitted":
                        update_data["status"] = "submitted"
                    elif ls_status == "not_started" and current_status == "unavailable":
                        update_data["status"] = "not_started"
                    elif ls_status == "in_progress" and current_status in ("not_started", "newly_assigned"):
                        update_data["status"] = "in_progress"
                    elif ls_status == "unavailable" and current_status == "newly_assigned":
                        update_data["status"] = "unavailable"

                    # Update due date if changed
                    if is_modified and assignment.get("due_date"):
                        update_data["due_date"] = assignment["due_date"]
                        update_data["description"] = assignment.get("description")

                    self.supabase.table("assignments").update(update_data).eq(
                        "id", existing_record["id"]
                    ).execute()

                    if is_modified:
                        summary["modified"] += 1
                        print(f"    [DB] UPDATED (modified)")
                    else:
                        summary["unchanged"] += 1
                        print(f"    [DB] UNCHANGED")

                else:
                    # Insert new assignment
                    # Use scraper status for definitive states, otherwise newly_assigned
                    scraped_status = assignment.get("status", "not_started")
                    insert_status = scraped_status if scraped_status in ("submitted", "in_progress", "unavailable") else "newly_assigned"

                    new_record = {
                        "title": assignment["title"],
                        "course_name": assignment["course_name"],
                        "due_date": assignment.get("due_date"),
                        "description": assignment.get("description"),
                        "link": assignment.get("link"),
                        "status": insert_status,
                        "is_modified": False,
                        "last_scraped_at": now,
                        "learning_suite_url": assignment.get("link"),
                        "assignment_type": assignment.get("assignment_type"),
                        "ls_cid": assignment.get("ls_cid"),
                    }

                    print(f"    [DB] INSERTING NEW RECORD:")
                    print(f"         Title: '{new_record['title']}'")
                    print(f"         Course: '{new_record['course_name']}'")
                    print(f"         Status: '{new_record['status']}'")
                    print(f"         Due: {new_record['due_date']}")
                    print(f"         CID: {new_record['ls_cid']}")

                    self.supabase.table("assignments").insert(new_record).execute()
                    summary["new"] += 1
                    print(f"    [DB] INSERTED SUCCESSFULLY")

            except Exception as e:
                print(f"    [DB ERROR] Error updating assignment '{assignment.get('title')}': {e}")
                summary["errors"] += 1

        print("\n" + "=" * 70)
        print(f">>> DATABASE UPDATE COMPLETE")
        print(f">>> New: {summary['new']}, Modified: {summary['modified']}, Unchanged: {summary['unchanged']}, Errors: {summary['errors']}")
        print("=" * 70)
        return summary

    def run(self, netid: str, password: str, update_db: bool = True) -> dict:
        """Run the full scraping process.

        Args:
            netid: BYU NetID
            password: BYU password
            update_db: Whether to update the database

        Returns:
            Result dictionary with assignments and summary
        """
        result = {
            "success": False,
            "assignments": [],
            "courses": [],
            "summary": {},
            "error": None,
            "warnings": []
        }

        try:
            # Login
            print("\n" + "=" * 70)
            print(">>> STARTING LOGIN PROCESS")
            print("=" * 70)

            if not self.login(netid, password):
                result["error"] = "Login failed - check credentials or complete MFA"
                self._save_debug_html("final_login_failed")
                return result

            print("\n>>> Login successful!")

            # Get courses
            print("\n" + "=" * 70)
            print(">>> GETTING COURSE LIST")
            print("=" * 70)

            result["courses"] = self.get_courses()

            if not result["courses"]:
                result["error"] = "No courses found - check if you're enrolled in any classes"
                result["warnings"].append("No courses were found on the Learning Suite home page")
                self._save_debug_html("no_courses_found")
                return result

            print(f"\n>>> Found {len(result['courses'])} courses")

            # Scrape assignments
            print("\n" + "=" * 70)
            print(">>> SCRAPING ASSIGNMENTS FROM ALL COURSES")
            print("=" * 70)

            result["assignments"] = self.scrape_all_courses()

            if not result["assignments"]:
                result["warnings"].append("No assignments were found across all courses")
                logger.warning("No assignments found - this could be normal if no assignments exist")

            # Update database if requested
            if update_db and result["assignments"]:
                print("\n" + "=" * 70)
                print(">>> UPDATING DATABASE")
                print("=" * 70)
                result["summary"] = self.update_database(result["assignments"])
            elif update_db:
                result["summary"] = {"new": 0, "modified": 0, "unchanged": 0, "errors": 0}

            result["success"] = True

            # Final summary
            print("\n" + "=" * 70)
            print(">>> SCRAPING COMPLETE")
            print(f">>> Courses: {len(result['courses'])}")
            print(f">>> Assignments: {len(result['assignments'])}")
            if result["warnings"]:
                print(f">>> Warnings: {len(result['warnings'])}")
                for w in result["warnings"]:
                    print(f"    - {w}")
            print("=" * 70)

        except KeyboardInterrupt:
            result["error"] = "Scraping interrupted by user"
            logger.info("Scraping interrupted by user")
        except Exception as e:
            logger.error(f"Scraper error: {e}")
            import traceback
            traceback.print_exc()
            result["error"] = str(e)
            self._save_debug_html("scraper_exception")

        finally:
            self.close()

        return result

    def close(self):
        """Close the browser."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            logger.info("Browser closed")
