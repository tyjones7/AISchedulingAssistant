"""
Throwaway test script for Phase 1: validate iCal feed data quality.
Run: cd backend && python3 test_ical.py
"""
from ical_client import fetch_and_parse

URL = "https://learningsuite.byu.edu/iCalFeed/ical.php?courseID=a_Z7LskkmWJz"
assignments = fetch_and_parse(URL, "Test Course")
print(f"Total: {len(assignments)}")
for a in assignments[:10]:
    print(f"  {a['due_date'][:10]}  {a['assignment_type']:<12}  {a['title'][:60]}")
