#!/usr/bin/env python3
"""
Clear all assignments from Supabase database.

Usage:
    python clear_assignments.py
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

    print("=" * 60)
    print("CLEARING ALL ASSIGNMENTS FROM DATABASE")
    print("=" * 60)

    # First, count existing assignments
    count_response = supabase.table("assignments").select("id", count="exact").execute()
    total_count = count_response.count if count_response.count else len(count_response.data)

    print(f"\nFound {total_count} assignments in database")

    if total_count == 0:
        print("Database is already empty!")
        return

    # Delete all assignments
    # Supabase requires a filter for delete, so we use a condition that matches all
    # We'll delete in batches by fetching IDs first
    print("\nDeleting all assignments...")

    # Fetch all IDs
    all_assignments = supabase.table("assignments").select("id").execute()

    deleted_count = 0
    for assignment in all_assignments.data:
        try:
            supabase.table("assignments").delete().eq("id", assignment["id"]).execute()
            deleted_count += 1
        except Exception as e:
            print(f"  Error deleting {assignment['id']}: {e}")

    print(f"\nDeleted {deleted_count} assignments")

    # Verify deletion
    verify_response = supabase.table("assignments").select("id", count="exact").execute()
    remaining = verify_response.count if verify_response.count else len(verify_response.data)

    if remaining == 0:
        print("\nDatabase cleared successfully!")
    else:
        print(f"\nWarning: {remaining} assignments still remain")

    print("=" * 60)


if __name__ == "__main__":
    main()
