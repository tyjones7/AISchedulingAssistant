#!/usr/bin/env python3
"""
Fix existing data in the database:
1. Build proper URLs with course ID (cid) for Learning Suite
2. Clean HTML from descriptions
3. Decode HTML entities in titles and descriptions

NOTE: This script requires the ls_cid column to exist in the database.
Run migrations/002_add_ls_cid_column.sql first if you haven't.
"""

import os
import re
import html
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

LEARNING_SUITE_URL = "https://learningsuite.byu.edu"


def extract_cid_from_url(url: str) -> str:
    """Extract course ID from a Learning Suite URL if present."""
    if not url:
        return None
    match = re.search(r'cid-([A-Za-z0-9_-]+)', url)
    return match.group(1) if match else None


def extract_assignment_id_from_url(url: str) -> str:
    """Extract assignment ID from a Learning Suite URL."""
    if not url:
        return None
    # Match /assignment/XXX or /exam/info/id-XXX patterns
    match = re.search(r'/assignment/([A-Za-z0-9_-]+)', url)
    if match:
        return match.group(1)
    match = re.search(r'/exam/info/id-([A-Za-z0-9_-]+)', url)
    if match:
        return match.group(1)
    return None


def build_proper_url(assignment_id: str, cid: str, is_exam: bool = False) -> str:
    """Build a proper Learning Suite URL with course ID."""
    if not assignment_id or not cid:
        return None
    if is_exam:
        return f"{LEARNING_SUITE_URL}/cid-{cid}/student/exam/info/id-{assignment_id}"
    return f"{LEARNING_SUITE_URL}/cid-{cid}/student/assignment/{assignment_id}"


def clean_description(description: str) -> str:
    """Clean HTML tags and entities from description."""
    if not description:
        return description

    # First decode HTML entities
    cleaned = html.unescape(description)

    # Remove HTML tags
    cleaned = re.sub(r'<[^>]+>', '', cleaned)

    # Clean up extra whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # Truncate if too long
    if len(cleaned) > 500:
        cleaned = cleaned[:500] + "..."

    return cleaned


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Error: SUPABASE_URL and SUPABASE_KEY must be set in .env file")
        return

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("=" * 80)
    print("FIXING EXISTING DATA IN DATABASE")
    print("=" * 80)

    # Get all assignments
    all_assignments = supabase.table("assignments").select("*").execute()

    if not all_assignments.data:
        print("\nNo assignments found in database!")
        return

    print(f"\nTotal assignments to process: {len(all_assignments.data)}")

    # PHASE 1: Collect CIDs from URLs that have them
    print("\n--- Phase 1: Collecting course CIDs from existing URLs ---")
    course_cids = {}
    for assignment in all_assignments.data:
        course_name = assignment.get("course_name", "")
        link = assignment.get("link", "")
        ls_cid = assignment.get("ls_cid")

        # Check if we already have CID stored
        if ls_cid and course_name:
            course_cids[course_name] = ls_cid
            continue

        # Try to extract CID from URL
        cid = extract_cid_from_url(link)
        if cid and course_name:
            course_cids[course_name] = cid
            print(f"  Found CID for '{course_name}': {cid}")

    print(f"\nCourse CID mappings found: {len(course_cids)}")
    for course, cid in course_cids.items():
        print(f"  {course}: {cid}")

    # PHASE 2: Fix URLs and other data
    print("\n--- Phase 2: Fixing assignments ---")
    fixed_count = 0
    urls_needing_cid = 0

    for assignment in all_assignments.data:
        needs_update = False
        update_data = {}

        course_name = assignment.get("course_name", "")
        cid = course_cids.get(course_name) or assignment.get("ls_cid")

        # Store the CID if we found one
        if cid and not assignment.get("ls_cid"):
            update_data["ls_cid"] = cid
            needs_update = True

        # Fix URL - build proper URL with CID
        original_link = assignment.get("link")
        if original_link:
            assignment_id = extract_assignment_id_from_url(original_link)
            is_exam = "/exam/" in original_link

            if assignment_id and cid:
                proper_url = build_proper_url(assignment_id, cid, is_exam)
                if proper_url and proper_url != original_link:
                    update_data["link"] = proper_url
                    update_data["learning_suite_url"] = proper_url
                    needs_update = True
                    print(f"\n[URL FIX] {assignment.get('title', 'Unknown')[:50]}")
                    print(f"  Before: {original_link}")
                    print(f"  After:  {proper_url}")
            elif assignment_id and not cid:
                urls_needing_cid += 1

        # Fix description
        original_desc = assignment.get("description")
        if original_desc:
            cleaned_desc = clean_description(original_desc)
            if cleaned_desc != original_desc:
                update_data["description"] = cleaned_desc
                needs_update = True
                print(f"\n[DESC FIX] {assignment.get('title', 'Unknown')[:50]}")
                print(f"  Had HTML: {bool(re.search(r'<[^>]+>', original_desc))}")
                print(f"  Preview: {cleaned_desc[:100]}...")

        # Fix title (decode HTML entities)
        original_title = assignment.get("title", "")
        cleaned_title = html.unescape(original_title)
        if cleaned_title != original_title:
            update_data["title"] = cleaned_title
            needs_update = True
            print(f"\n[TITLE FIX]")
            print(f"  Before: {original_title}")
            print(f"  After:  {cleaned_title}")

        # Apply updates
        if needs_update:
            supabase.table("assignments").update(update_data).eq(
                "id", assignment["id"]
            ).execute()
            fixed_count += 1

    print("\n" + "=" * 80)
    print(f"DONE! Fixed {fixed_count} assignments")
    if urls_needing_cid > 0:
        print(f"\nWARNING: {urls_needing_cid} assignments have URLs that need a course CID")
        print("Run the scraper again to get proper CIDs for all courses:")
        print("  cd backend && ./venv/bin/python test_scraper.py --debug")
    print("=" * 80)


if __name__ == "__main__":
    main()
