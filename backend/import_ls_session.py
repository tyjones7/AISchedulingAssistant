#!/usr/bin/env python3
"""
Import your BYU Learning Suite session to the deployed CampusAI backend.

Run this script on your local machine (where Touch ID / Duo works normally)
to authenticate Learning Suite and store the session in the cloud.

Usage:
  python3 import_ls_session.py

You will be asked to:
  1. Enter your CampusAI account email + password (to authenticate with the API)
  2. Log in to Learning Suite in the Chrome window that opens
     (Touch ID and regular Duo both work since it runs on YOUR computer)
  3. The session is automatically uploaded to the deployed backend

Requirements:
  pip install selenium requests python-dotenv
  (chromedriver must match your Chrome version — or install chromedriver-autoinstaller)
"""

import sys
import os
import re
import time
import json
import requests
from dotenv import load_dotenv

load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL", "https://campusai-8xmn.onrender.com")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")


def sign_in_supabase(email: str, password: str) -> str:
    """Sign in to Supabase and return the JWT access token."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set in .env")
        sys.exit(1)
    url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
    resp = requests.post(
        url,
        json={"email": email, "password": password},
        headers={"apikey": SUPABASE_KEY},
        timeout=15,
    )
    if not resp.ok:
        print(f"ERROR: Sign-in failed ({resp.status_code}): {resp.text}")
        sys.exit(1)
    return resp.json()["access_token"]


def open_browser_and_capture(token: str):
    """Open a visible Chrome window, let user log in to LS, return (cookies, base_url)."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError:
        print("ERROR: selenium not installed. Run: pip install selenium")
        sys.exit(1)

    # Try to auto-install chromedriver if available
    try:
        import chromedriver_autoinstaller
        chromedriver_autoinstaller.install()
    except ImportError:
        pass  # Not installed — hope chromedriver is on PATH

    options = Options()
    options.add_argument("--start-maximized")
    # NOTE: do NOT add --headless — Touch ID only works in a visible browser

    print("\nOpening Chrome. Please log in to BYU Learning Suite in the window that appears.")
    print("Use Touch ID, Duo, or whatever works on your computer.")
    print("The window will capture your session automatically after login.\n")

    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        print(f"ERROR: Could not start Chrome: {e}")
        print("Make sure chromedriver matches your Chrome version:")
        print("  pip install chromedriver-autoinstaller")
        sys.exit(1)

    driver.get("https://learningsuite.byu.edu")

    print("Waiting for you to complete login (up to 5 minutes)...")
    for i in range(150):
        time.sleep(2)
        try:
            current_url = driver.current_url
            if re.match(r'https://learningsuite\.byu\.edu/\.[A-Za-z0-9]+', current_url):
                print(f"Login detected!")
                break
        except Exception:
            pass
    else:
        print("ERROR: Timed out waiting for login.")
        driver.quit()
        sys.exit(1)

    # Extract the dynamic base URL
    match = re.match(r'(https://learningsuite\.byu\.edu/\.[A-Za-z0-9]+)', driver.current_url)
    base_url = match.group(1) if match else driver.current_url

    # Capture all cookies (including HttpOnly — Selenium can read these)
    cookies = driver.get_cookies()
    print(f"Captured {len(cookies)} cookies from Learning Suite.")

    driver.quit()
    return cookies, base_url


def upload_session(token: str, cookies: list, base_url: str):
    """POST cookies + base_url to the deployed backend."""
    url = f"{BACKEND_URL}/auth/import-ls-session"
    print(f"\nUploading session to {BACKEND_URL}...")
    resp = requests.post(
        url,
        json={"cookies": cookies, "base_url": base_url},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30,
    )
    if resp.ok:
        print("Session uploaded successfully!")
        print("Open the CampusAI app and click 'Sync' to load your assignments.")
    else:
        print(f"ERROR: Upload failed ({resp.status_code}): {resp.text}")
        sys.exit(1)


if __name__ == "__main__":
    print("=== CampusAI — Learning Suite Session Import ===")
    print(f"Backend: {BACKEND_URL}\n")

    email = input("CampusAI account email: ").strip()
    password = input("CampusAI account password: ").strip()

    print("Signing in to CampusAI...")
    token = sign_in_supabase(email, password)
    print("Signed in.\n")

    cookies, base_url = open_browser_and_capture(token)
    upload_session(token, cookies, base_url)
