#!/usr/bin/env python3
"""
Diagnostic script to check what's actually in the Supabase database.
"""

import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Error: SUPABASE_URL and SUPABASE_KEY must be set in .env file")
        return

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("=" * 80)
    print("SUPABASE DATABASE DIAGNOSTIC")
    print("=" * 80)

    # Get total count
    count_response = supabase.table("assignments").select("id", count="exact").execute()
    total_count = count_response.count if count_response.count else len(count_response.data)
    print(f"\nTotal assignments in database: {total_count}")

    # Get all assignments
    all_assignments = supabase.table("assignments").select("*").order("course_name").execute()

    if not all_assignments.data:
        print("\nNo assignments found in database!")
        return

    # Group by course
    print("\n" + "=" * 80)
    print("ASSIGNMENTS GROUPED BY COURSE")
    print("=" * 80)

    by_course = {}
    for a in all_assignments.data:
        course = a.get('course_name', 'UNKNOWN')
        if course not in by_course:
            by_course[course] = []
        by_course[course].append(a)

    for course_name, assignments in sorted(by_course.items()):
        print(f"\n{'='*60}")
        print(f"COURSE: {course_name} ({len(assignments)} assignments)")
        print(f"{'='*60}")

        for a in assignments:
            print(f"\n  Title: {a.get('title', 'N/A')}")
            print(f"  Status: {a.get('status', 'N/A')}")
            print(f"  Due Date: {a.get('due_date', 'N/A')}")
            print(f"  ID: {a.get('id', 'N/A')}")
            if a.get('ls_cid'):
                print(f"  LS Course ID: {a.get('ls_cid')}")
            if a.get('ls_assignment_id'):
                print(f"  LS Assignment ID: {a.get('ls_assignment_id')}")

    # Summary statistics
    print("\n" + "=" * 80)
    print("SUMMARY STATISTICS")
    print("=" * 80)

    # By course
    print("\nAssignments per course:")
    for course_name, assignments in sorted(by_course.items()):
        print(f"  {course_name}: {len(assignments)}")

    # By status
    status_counts = {}
    for a in all_assignments.data:
        s = a.get('status', 'unknown')
        status_counts[s] = status_counts.get(s, 0) + 1

    print("\nAssignments per status:")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")

    # Due dates
    print("\nDue dates distribution:")
    date_counts = {}
    for a in all_assignments.data:
        d = a.get('due_date', 'unknown')
        # Just show the date part if it's a timestamp
        if d and 'T' in str(d):
            d = str(d).split('T')[0]
        date_counts[d] = date_counts.get(d, 0) + 1

    for date, count in sorted(date_counts.items()):
        print(f"  {date}: {count} assignments")

    print("\n" + "=" * 80)
    print("END OF DIAGNOSTIC")
    print("=" * 80)


if __name__ == "__main__":
    main()
