#!/usr/bin/env python3
"""
LS API Discovery Script
Captures all background HTTP requests Learning Suite makes when you browse it.
Run from the backend directory: python3 discover_ls_api.py
"""
import json
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

OUTPUT = os.path.join(os.path.dirname(__file__), "ls_api_discovery.json")
LS_URL = "https://learningsuite.byu.edu"

# Track state across drain calls
_pending_requests = {}   # requestId -> request data (waiting for response)
_seen_ids = set()        # requestIds we've already finalized


def setup_driver():
    opts = Options()
    opts.add_argument("--window-size=1440,900")
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    svc = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=svc, options=opts)
    driver.execute_cdp_cmd("Network.enable", {})
    return driver


def inject_stored_cookies(driver):
    """Inject saved auth cookies so the user doesn't need to log in again."""
    try:
        import auth_store
        cookies, base_url = auth_store.get_session_data()
        if not cookies:
            return False
        driver.get("about:blank")
        injected = 0
        for c in cookies:
            try:
                driver.execute_cdp_cmd("Network.setCookie", {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c.get("domain", "learningsuite.byu.edu"),
                    "path": c.get("path", "/"),
                    "secure": bool(c.get("secure", False)),
                    "httpOnly": bool(c.get("httpOnly", False)),
                })
                injected += 1
            except Exception:
                pass
        print(f"  Injected {injected}/{len(cookies)} cookies from stored session")
        return True
    except Exception as e:
        print(f"  No stored session available ({e})")
        return False


def drain_performance_log(driver):
    """
    Pull new entries from Chrome's performance log and return finalized requests
    (those that have both a request and a response recorded).
    """
    global _pending_requests, _seen_ids

    finalized = []

    try:
        entries = driver.get_log("performance")
    except Exception:
        return finalized

    for entry in entries:
        try:
            msg = json.loads(entry["message"])["message"]
            method = msg.get("method", "")
            params = msg.get("params", {})

            if method == "Network.requestWillBeSent":
                req = params.get("request", {})
                url = req.get("url", "")
                req_id = params.get("requestId", "")

                # SAFETY: never capture CAS/auth requests — they contain credentials
                if "cas.byu.edu" in url or "duo" in url or "saml" in url.lower():
                    continue

                # Only track LS requests we haven't seen yet
                if "learningsuite.byu.edu" in url and req_id not in _seen_ids:
                    _pending_requests[req_id] = {
                        "requestId": req_id,
                        "url": url,
                        "method": req.get("method", "GET"),
                        "postData": req.get("postData"),
                        "status": None,
                        "mimeType": None,
                        "responseBody": None,
                    }

            elif method == "Network.responseReceived":
                req_id = params.get("requestId", "")
                if req_id in _pending_requests:
                    resp = params.get("response", {})
                    _pending_requests[req_id]["status"] = resp.get("status")
                    _pending_requests[req_id]["mimeType"] = resp.get("mimeType", "")

            elif method == "Network.loadingFinished":
                req_id = params.get("requestId", "")
                if req_id in _pending_requests and req_id not in _seen_ids:
                    record = _pending_requests.pop(req_id)
                    _seen_ids.add(req_id)

                    # Try to fetch response body while it's still in CDP buffer
                    try:
                        result = driver.execute_cdp_cmd(
                            "Network.getResponseBody", {"requestId": req_id}
                        )
                        body = result.get("body", "")
                        record["responseBody"] = body[:3000]
                    except Exception:
                        record["responseBody"] = None

                    finalized.append(record)

        except Exception:
            pass

    return finalized


def main():
    print("=" * 55)
    print("  Learning Suite API Discovery")
    print("=" * 55)
    print()

    driver = setup_driver()

    # Try stored cookies first
    print("Looking for a stored auth session...")
    had_cookies = inject_stored_cookies(driver)

    print(f"Opening {LS_URL}...")
    driver.get(LS_URL)
    time.sleep(2)

    # If no cookies or they didn't work, wait for manual login
    current = driver.current_url
    if not had_cookies or "cas.byu.edu" in current or "duo" in current.lower():
        print()
        print("Please log in to Learning Suite in the browser window.")
        print("Waiting up to 2 minutes for login...")
        try:
            WebDriverWait(driver, 120).until(
                lambda d: "learningsuite.byu.edu" in d.current_url
                          and "cas.byu.edu" not in d.current_url
                          and "duo" not in d.current_url.lower()
            )
            print("Logged in successfully!")
        except Exception:
            print("Login timed out — continuing anyway.")
    else:
        print("Session active!")

    print()
    print("─" * 55)
    print("  NOW: Click on ONE course → click 'Grades' in the sidebar")
    print("  The script will capture all background API calls.")
    print("  You have 90 seconds.")
    print("─" * 55)
    print()

    all_requests = []
    start = time.time()
    DURATION = 90

    while time.time() - start < DURATION:
        time.sleep(1)
        new = drain_performance_log(driver)
        for r in new:
            all_requests.append(r)
            url = r["url"].replace("https://learningsuite.byu.edu", "")
            method = r.get("method", "?")
            status = r.get("status") or "?"
            mime = r.get("mimeType") or ""

            # Print every LS request so you can see what's happening
            print(f"  [{method:4}] {url[:70]:<70}  {status}")
            if r.get("postData"):
                print(f"         Body: {r['postData'][:120]}")

        elapsed = int(time.time() - start)
        remaining = DURATION - elapsed
        if remaining in (60, 30, 10) and remaining > 0:
            print(f"\n  ({remaining}s remaining — keep browsing)\n")

    print()
    print(f"Done. Captured {len(all_requests)} LS requests total.")

    # Separate the interesting API calls from static assets
    api_requests = [
        r for r in all_requests
        if "ajax.php" in r.get("url", "")
        or r.get("mimeType", "").startswith("application/json")
        or r.get("mimeType", "") == "text/json"
        or (r.get("responseBody") or "").lstrip().startswith(("{", "["))
    ]

    print(f"API/JSON requests: {len(api_requests)}")
    print()
    print("API requests found:")
    for r in api_requests:
        url = r["url"].replace("https://learningsuite.byu.edu", "")
        print(f"  [{r.get('method','?')}] {url}")
        if r.get("postData"):
            print(f"         Body: {r['postData'][:200]}")
        if r.get("responseBody"):
            preview = r["responseBody"][:300].replace('\n', ' ')
            print(f"         Response: {preview}")
        print()

    output = {
        "summary": {
            "total_requests": len(all_requests),
            "api_requests": len(api_requests),
        },
        "api_requests": api_requests,
        "all_requests": all_requests,
    }

    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Full results saved to: {OUTPUT}")
    driver.quit()


if __name__ == "__main__":
    main()
