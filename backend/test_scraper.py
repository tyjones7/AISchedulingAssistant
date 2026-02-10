#!/usr/bin/env python3
"""
Test script for Learning Suite Scraper

Usage:
    python test_scraper.py           # Normal mode
    python test_scraper.py --debug   # Debug mode with verbose logging

Make sure to set BYU_NETID and BYU_PASSWORD in your .env file before running.
"""

import os
import sys
import logging
from dotenv import load_dotenv

# Force unbuffered output for real-time logging
sys.stdout.reconfigure(line_buffering=True)

# Add the backend directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper.learning_suite_scraper import LearningSuiteScraper

def main():
    load_dotenv()

    # Enable debug logging if --debug flag is passed
    if "--debug" in sys.argv:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("scraper.learning_suite_scraper").setLevel(logging.DEBUG)
        print("DEBUG MODE ENABLED - verbose logging active\n")

    print("\n" + "=" * 70)
    print("DETAILED SCRAPER DEBUG RUN")
    print("=" * 70)
    print("This run will show detailed logging for each assignment including:")
    print("  - Which course is being scraped")
    print("  - Each assignment title found")
    print("  - Button text for each assignment")
    print("  - How status is being determined")
    print("  - What's being saved to the database")
    print("=" * 70 + "\n")

    netid = os.getenv("BYU_NETID")
    password = os.getenv("BYU_PASSWORD")

    if not netid or not password:
        print("Error: BYU_NETID and BYU_PASSWORD must be set in .env file")
        print("\nCreate a .env file in the backend folder with:")
        print("  BYU_NETID=your_netid_here")
        print("  BYU_PASSWORD=your_password_here")
        sys.exit(1)

    print("=" * 60)
    print("Learning Suite Scraper Test")
    print("=" * 60)
    print(f"\nUsing NetID: {netid}")
    print("Starting scraper (headless=False so you can see the browser)...\n")

    # Create scraper with visible browser for testing
    scraper = LearningSuiteScraper(headless=False)

    try:
        # Run the scraper
        result = scraper.run(netid, password, update_db=True)

        print("\n" + "=" * 60)
        print("RESULTS")
        print("=" * 60)

        if result["success"]:
            print(f"\n✓ Scraping completed successfully!")

            # Show warnings if any
            if result.get("warnings"):
                print(f"\n⚠ Warnings ({len(result['warnings'])}):")
                for warning in result["warnings"]:
                    print(f"  - {warning}")

            print(f"\nCourses found: {len(result['courses'])}")
            for course in result['courses']:
                print(f"  - {course['name']} (cid-{course['cid']})")

            print(f"\nTotal assignments: {len(result['assignments'])}")

            if result["summary"]:
                print(f"\nDatabase update summary:")
                print(f"  - New:       {result['summary'].get('new', 0)}")
                print(f"  - Modified:  {result['summary'].get('modified', 0)}")
                print(f"  - Unchanged: {result['summary'].get('unchanged', 0)}")
                print(f"  - Errors:    {result['summary'].get('errors', 0)}")

            # Show ALL assignments grouped by course
            if result["assignments"]:
                print("\n" + "-" * 60)
                print("ALL ASSIGNMENTS BY COURSE:")
                print("-" * 60)

                # Group by course
                by_course = {}
                for assignment in result["assignments"]:
                    course = assignment['course_name']
                    if course not in by_course:
                        by_course[course] = []
                    by_course[course].append(assignment)

                for course_name, assignments in by_course.items():
                    print(f"\n{'='*60}")
                    print(f"COURSE: {course_name}")
                    print(f"{'='*60}")

                    # Group by status for summary
                    status_counts = {}
                    for a in assignments:
                        s = a['status']
                        status_counts[s] = status_counts.get(s, 0) + 1

                    print(f"Status summary: {status_counts}")
                    print()

                    for i, assignment in enumerate(assignments):
                        status_marker = {
                            'submitted': '✓',
                            'in_progress': '◐',
                            'not_started': '○',
                            'unavailable': '✗',
                            'newly_assigned': '★'
                        }.get(assignment['status'], '?')

                        print(f"  {status_marker} {assignment['title']}")
                        print(f"      Button: '{assignment.get('button_text', 'N/A')}' -> Status: {assignment['status']}")
                        if assignment.get('due_date'):
                            print(f"      Due: {assignment['due_date']}")

                # FINAL TOTALS COMPARISON
                print("\n" + "=" * 60)
                print("FINAL TOTALS BY COURSE (for comparison)")
                print("=" * 60)
                print(f"{'Course':<40} {'Scraped':>10}")
                print("-" * 60)
                for course_name in sorted(by_course.keys()):
                    count = len(by_course[course_name])
                    # Extract short course code
                    short_name = course_name.split(' - ')[0] if ' - ' in course_name else course_name
                    print(f"{short_name:<40} {count:>10}")
                print("-" * 60)
                print(f"{'TOTAL':<40} {len(result['assignments']):>10}")
                print("=" * 60)

        else:
            print(f"\n✗ Scraping failed: {result.get('error', 'Unknown error')}")

    except KeyboardInterrupt:
        print("\n\nScraping interrupted by user")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        raise
    finally:
        scraper.close()

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
